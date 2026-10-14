"""Resolução de entidades: do nome que o LLM devolve para uma `Entity` da BD.

Regras (cada decisão devolve um dict de debug com os candidatos):
1. Match normalizado (entities.normalize) contra `EntityAlias.normalized`, entidades activas ou por rever; as
   fundidas seguem `merged_into` até à entidade final.
2. Primeiro pelo `canonical_name`; só se não houver nenhum candidato, pelo nome como aparece no texto. Assim
   "Costa" (ambíguo) com canonical "António Costa" (único) liga à entidade certa.
3. Os candidatos filtram-se pelo tipo: o mesmo tipo; senão o mesmo grupo (pessoa | local | colectivas).
4. Um candidato → liga. Nenhum → cria a entidade `por_rever` com os aliases (nome + canonical).
5. Vários (ambíguo) → **não escolhe**: cria (ou reutiliza) uma entidade `por_rever` marcada como ambígua, com os
   candidatos no debug, para o backoffice fundir com a certa. A marca (`debug.ambiguous_key`) faz com que as
   menções seguintes do mesmo nome ambíguo caiam na mesma entidade provisória, em vez de criarem mais uma.
6. Meios de comunicação: antes dos aliases, tenta o `Site` (nome, slug ou domínio) e liga ao `Site.entity`.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from entities.models import Entity, EntityAlias
from entities.normalize import normalize

# O schema da análise usa `meio_comunicacao`; o modelo guarda `meio` (é o valor que o seed das fontes usa).
TYPE_MAP = {"meio_comunicacao": "meio"}
VALID_TYPES = {t for t, _ in Entity.TYPE_CHOICES}
_GROUPS = {"pessoa": "pessoa", "local": "local"}


def map_type(llm_type: str | None) -> str:
    t = TYPE_MAP.get(llm_type or "", llm_type or "outro")
    return t if t in VALID_TYPES else "outro"


def _group(t: str) -> str:
    return _GROUPS.get(t, "colectiva")


def final_entity(entity: Entity) -> Entity:
    seen = set()
    while entity.merged_into_id and entity.pk not in seen:
        seen.add(entity.pk)
        entity = entity.merged_into
    return entity


def _candidates(key: str) -> list[Entity]:
    if not key:
        return []
    out = {}
    for alias in EntityAlias.objects.filter(normalized=key).select_related("entity", "entity__merged_into"):
        ent = final_entity(alias.entity)
        if ent.status != "merged":
            out[ent.pk] = ent
    return list(out.values())


def _by_type(cands: list[Entity], etype: str) -> tuple[list[Entity], str]:
    same = [c for c in cands if c.type == etype]
    if same:
        return same, "mesmo tipo"
    group = [c for c in cands if _group(c.type) == _group(etype)]
    if group:
        return group, f"mesmo grupo ({_group(etype)})"
    return [], "tipos incompatíveis"


def _describe(ents: list[Entity]) -> list[dict]:
    return [{"id": e.pk, "name": e.canonical_name, "type": e.type, "status": e.status} for e in ents]


def match_site(keys: list[str]):
    """Site cujo nome, slug ou domínio coincide com um dos nomes normalizados."""
    from sources.models import Site

    for site in Site.objects.select_related("entity"):
        host = urlsplit(site.base_url).hostname or ""
        host = host.removeprefix("www.")
        names = {normalize(site.name), normalize(site.slug), normalize(host), normalize(host.split(".")[0])}
        if any(k and k in names for k in keys):
            return site
    return None


def add_alias(entity: Entity, name: str) -> bool:
    key = normalize(name)
    if not key:
        return False
    _, created = EntityAlias.objects.get_or_create(entity=entity, normalized=key, defaults={"alias": name[:300]})
    return created


def resolve(name: str, canonical_name: str | None, etype: str, *, is_public: bool | None = None,
            place_level: str = "", analysis_id: int | None = None, create: bool = True) -> tuple[Entity | None, dict]:
    """(entidade, debug). `etype` já no vocabulário do modelo (usar map_type antes)."""
    canonical = (canonical_name or "").strip() or (name or "").strip()
    name = (name or "").strip() or canonical
    keys = list(dict.fromkeys(k for k in (normalize(canonical), normalize(name)) if k))
    debug: dict = {"name": name, "canonical_name": canonical, "type": etype, "keys": keys}

    if etype == "meio":
        site = match_site(keys)
        if site and site.entity_id:
            ent = final_entity(site.entity)
            debug.update(decision="ligada ao meio monitorizado", site=site.slug, entity_id=ent.pk)
            return ent, debug

    for stage, key in (("canonical_name", keys[0] if keys else ""), ("name", keys[-1] if len(keys) > 1 else "")):
        raw = _candidates(key)
        if not raw:
            continue
        cands, why = _by_type(raw, etype)
        debug.setdefault("stages", []).append({"stage": stage, "key": key, "candidates": _describe(raw),
                                               "after_type_filter": [c.pk for c in cands], "type_filter": why})
        if len(cands) == 1:
            ent = cands[0]
            if stage == "canonical_name" and name and normalize(name) != key and ent.status == "active":
                debug["alias_added"] = add_alias(ent, name)   # aprende "Ventura" → André Ventura
            debug.update(decision=f"um candidato ({stage}, {why})", entity_id=ent.pk)
            return ent, debug
        if len(cands) > 1:
            placeholder = next((c for c in cands if c.status == "por_rever"
                                and (c.debug or {}).get("ambiguous_key") == key), None)
            if placeholder:
                debug.update(decision="ambíguo: reutiliza a entidade provisória deste nome", entity_id=placeholder.pk)
                return placeholder, debug
            if not create:
                debug.update(decision="ambíguo, sem criação")
                return None, debug
            ent = _create(canonical, name, etype, is_public, place_level, analysis_id,
                          {"reason": "ambíguo", "ambiguous_key": key, "candidates": _describe(cands)})
            debug.update(decision="ambíguo: criada entidade por rever (não escolhe)", entity_id=ent.pk)
            return ent, debug
        # Candidatos só de outro tipo: passa ao nome do texto ou cria.

    if not create:
        debug.update(decision="sem correspondência, sem criação")
        return None, debug
    ent = _create(canonical, name, etype, is_public, place_level, analysis_id,
                  {"reason": "sem correspondência", "candidates": debug.get("stages", [])})
    debug.update(decision="sem correspondência: criada entidade por rever", entity_id=ent.pk)
    return ent, debug


def _create(canonical, name, etype, is_public, place_level, analysis_id, extra) -> Entity:
    ent = Entity.objects.create(
        canonical_name=canonical[:300], type=etype, is_public=is_public, place_level=place_level or "",
        status="por_rever", debug={"created_by_analysis": analysis_id, **extra},
    )
    for alias in {canonical, name}:
        add_alias(ent, alias)
    return ent
