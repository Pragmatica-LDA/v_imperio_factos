"""Análise LLM de uma versão: orçamento, pedido ao provider, validação e catalogação (entidades, fontes, temas).

Fluxo de `analyze(version_id)`:
1. Idempotência: se já há uma análise feita desta versão com o mesmo provider/modelo/prompt, não faz nada.
2. Notícia não activa ou sem corpo: análise `skipped`.
3. Orçamento: análises de hoje (UTC, estados running/done/failed) contra `analysis.daily_limit`; esgotado →
   `skipped_budget` (o `drain` retoma). A contagem e a passagem a `running` fazem-se sob um advisory lock.
4. Pedido único ao provider (benchmark/llm ou fake), JSON validado contra o schema do benchmark; resposta
   inválida → até `analysis.repair_attempts` novos pedidos com os erros.
5. Falha → `failed` com o erro; o `drain` repete até `analysis.max_attempts`.
6. Sucesso → entidades, locais, fontes, temas, diff face à análise anterior e nova cadência das revisitas.
"""

from __future__ import annotations

import logging
import zlib
from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from analysis import prompts
from analysis.llm import ProviderError, get_provider, load_config, parse_json
from analysis.models import Analysis, CitedSource
from core import parameters
from crawl.models import Version
from entities.models import ArticleEntity
from entities.normalize import normalize
from entities.resolve import map_type, resolve
from topics.models import ArticleTopic
from topics.resolve import get_edition, resolve_path

log = logging.getLogger(__name__)

BUDGET_LOCK = zlib.crc32(b"factos.analysis.budget")
COUNTED = ("running", "done", "failed")
RETRYABLE = ("pending", "skipped_budget", "failed")

REPAIR_TEMPLATE = (
    "\n\n---\nA tua resposta anterior a este pedido não passou a validação do schema:\n{errors}\n"
    "Devolve de novo a análise completa, em JSON válido segundo o schema."
)


# --- Orçamento --------------------------------------------------------------------------------------------------

def today_start(now: datetime | None = None) -> datetime:
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    return datetime.combine(now.date(), time.min, tzinfo=dt_timezone.utc)


def used_today(now: datetime | None = None) -> int:
    return Analysis.objects.filter(status__in=COUNTED, started_at__gte=today_start(now)).count()


def budget_left(now: datetime | None = None) -> int:
    return max(0, int(parameters.get("analysis.daily_limit")) - used_today(now))


def _lock_budget() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [BUDGET_LOCK])


# --- Entrada principal ------------------------------------------------------------------------------------------

def analyze(version_id: int, force: bool = False) -> dict:
    """Analisa a versão. `force=True` (botão "Analisar agora") repete mesmo que já exista uma análise feita."""
    version = Version.objects.select_related("article", "article__site").get(pk=version_id)
    article = version.article
    cfg = load_config()
    ident = {"provider": cfg.provider, "model": cfg.model_id, "prompt_version": prompts.PROMPT_VERSION}

    done = Analysis.objects.filter(version=version, status="done", **ident).first()
    if done and not force:
        return {"status": "done", "analysis_id": done.pk, "skipped": "já analisada"}

    # Reutiliza a última linha não feita desta versão (pendente, adiada, falhada, ignorada), seja qual for o modelo.
    row = Analysis.objects.filter(version=version).exclude(status="done").order_by("-created_at").first()
    now = timezone.now()
    if force and row and row.status in ("running", "failed"):
        row.attempts = 0
    elif row and row.status == "running" and row.started_at and \
            now - row.started_at < timedelta(minutes=float(parameters.get("analysis.stale_running_min"))):
        return {"status": "running", "analysis_id": row.pk}
    if row and row.status == "failed" and row.attempts >= int(parameters.get("analysis.max_attempts")):
        return {"status": "failed", "analysis_id": row.pk, "skipped": "tentativas esgotadas"}
    row = row or Analysis(version=version)
    row.provider, row.model, row.prompt_version = cfg.provider, cfg.model_id, prompts.PROMPT_VERSION

    if article.status != "active" or not any((b.get("text") or "").strip() for b in (version.content or {}).get("body") or []):
        row.status = "skipped"
        row.error = f"notícia {article.status}" if article.status != "active" else "corpo vazio"
        row.finished_at = now
        row.save()
        return {"status": "skipped", "analysis_id": row.pk, "reason": row.error}

    with transaction.atomic():
        _lock_budget()
        if budget_left(now) <= 0:
            row.status, row.error = "skipped_budget", f"limite diário ({parameters.get('analysis.daily_limit')}) esgotado"
            row.save()
            return {"status": "skipped_budget", "analysis_id": row.pk}
        row.status, row.started_at, row.finished_at, row.error = "running", now, None, ""
        row.attempts += 1
        row.save()

    candidates = prompts.topic_candidates()
    system, user, info = prompts.build(version, candidates)
    try:
        output, usage, raw = _call(cfg, system, user, word_count=version.word_count or len((version.text or "").split()))
    except Exception as exc:  # noqa: BLE001 — ProviderError ou falha inesperada do SDK: fica registada e o drain repete
        msg = str(exc) if isinstance(exc, ProviderError) else f"{type(exc).__name__}: {exc}"
        row.status, row.error, row.finished_at = "failed", msg[:5000], timezone.now()
        row.usage = getattr(exc, "usage", {}) or row.usage
        row.raw_response = getattr(exc, "raw", None)
        row.debug = {"prompt": info, "topic_candidates": [c["path"] for c in candidates],
                     "attempts": (row.usage or {}).get("calls", [])}
        row.save()
        log.warning("análise %s da versão %s falhou: %s", row.pk, version.pk, exc)
        return {"status": "failed", "analysis_id": row.pk, "error": row.error}

    with transaction.atomic():
        _persist(row, version, output, usage, raw, candidates, info)
    _reschedule(article)
    return {"status": "done", "analysis_id": row.pk, "entities": row.entities.count(), "topics": row.topics.count()}


def empty_errors(output: dict, word_count: int) -> list[str]:
    """Resposta "stub" (ex.: Sonnet 5.5 com structured outputs devolve listas vazias com stop_reason=end_turn):
    sem entidades nem temas numa notícia com mais de `analysis.min_words_expect_entities` palavras é inválida."""
    min_words = int(parameters.get("analysis.min_words_expect_entities"))
    if word_count > min_words and not output.get("entities") and not output.get("themes"):
        return [f"<raiz>: resposta vazia (sem entidades nem temas) numa notícia com {word_count} palavras; "
                "cataloga as entidades e os temas da notícia"]
    return []


def _call(cfg, system: str, user: str, word_count: int = 0) -> tuple[dict, dict, str]:
    """Pedido + parse + validação (schema + resposta vazia), com até `analysis.repair_attempts` reparações
    (reenvia o pedido com os erros). Erros finais sobem como ProviderError (com usage e raw); cada tentativa
    fica em usage["calls"] com os seus erros."""
    provider = get_provider(cfg)
    repairs = int(parameters.get("analysis.repair_attempts"))
    usage = {"tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "repairs": 0, "calls": []}
    prompt_user, errors, text = user, [], ""
    for attempt in range(repairs + 1):
        result = provider.analyse(system, prompt_user, prompts.OUTPUT_SCHEMA)
        text = result.text
        usage["tokens_in"] += result.tokens_in or 0
        usage["tokens_out"] += result.tokens_out or 0
        usage["latency_ms"] += result.latency_ms or 0
        call = {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                "latency_ms": result.latency_ms, "meta": result.meta, "errors": []}
        usage["calls"].append(call)
        usage["meta"] = result.meta
        usage["repairs"] = attempt
        try:
            output = parse_json(text)
        except ValueError as exc:
            errors = [f"JSON inválido: {exc}"]
        else:
            errors = prompts.validate(output, prompts.OUTPUT_SCHEMA)
            if not errors and isinstance(output, dict):
                errors = empty_errors(output, word_count)
            if not errors:
                return output, usage, text
        call["errors"] = errors[:15]
        if errors and len(usage["calls"]) == 1:
            call["raw_head"] = text[:500]
        prompt_user = user + REPAIR_TEMPLATE.format(errors="\n".join(f"- {e}" for e in errors[:15]))
    exc = ProviderError("resposta inválida: " + "; ".join(errors[:10]))
    exc.usage, exc.raw = usage, text
    raise exc


# --- Persistência -----------------------------------------------------------------------------------------------

def _persist(row: Analysis, version, output: dict, usage: dict, raw: str, candidates: list[dict], info: dict) -> None:
    # Uma análise repetida (ex.: falhou a meio de uma versão anterior do código) começa limpa.
    row.entities.all().delete()
    row.sources.all().delete()
    row.topics.all().delete()

    llm_debug = output.get("debug") or {}
    dbg: dict = {
        "llm": llm_debug,
        "prompt": info,
        "attempts": [{k: c.get(k) for k in ("errors", "tokens_in", "tokens_out", "latency_ms")}
                     for c in usage.get("calls", [])],
        "topic_candidates": [c["path"] for c in candidates],
        "entities": [], "locations": [], "sources": [], "themes": [],
    }

    resolved: dict[str, object] = {}       # canonical/nome normalizado → Entity (desta análise)
    links: dict[int, ArticleEntity] = {}    # entity_id → ArticleEntity

    text = version.text or ""
    for e in output.get("entities") or []:
        if not (e.get("name") or e.get("canonical_name") or "").strip():
            dbg["entities"].append({"llm": e, "decision": "descartada: sem nome"})
            continue
        etype = map_type(e.get("type"))
        ent, rdbg = resolve(e.get("name"), e.get("canonical_name"), etype, is_public=e.get("is_public"),
                            analysis_id=row.pk)
        for k in (e.get("canonical_name"), e.get("name")):
            if k:
                resolved[normalize(k)] = ent
        position = (e.get("position_at_date") or "").strip()
        evidence = (e.get("sentiment_reason") or "").strip()
        item_debug = {"resolution": rdbg, "llm": e,
                      "position_in_text": bool(position) and normalize(position) in normalize(text)}
        link = links.get(ent.pk)
        if link:   # duas entradas do LLM para a mesma entidade: junta papéis
            link.roles = list(dict.fromkeys([*link.roles, *(e.get("roles") or [])]))
            link.evidence = "\n".join(x for x in (link.evidence, evidence) if x)
            link.debug.setdefault("merged", []).append(item_debug)
            link.save()
        else:
            links[ent.pk] = ArticleEntity.objects.create(
                analysis=row, entity=ent, name_in_text=(e.get("name") or ent.canonical_name)[:300],
                roles=list(dict.fromkeys(e.get("roles") or [])), position_at_time=position[:300],
                sentiment=e.get("sentiment") or "", sentiment_score=_score(e.get("sentiment_score")),
                is_location=etype == "local", evidence=evidence, debug=item_debug,
            )
        dbg["entities"].append({"name": e.get("name"), "entity_id": ent.pk, "decision": rdbg.get("decision")})

    for loc in output.get("locations") or []:
        name = (loc.get("name") or "").strip()
        if not name:
            continue
        level = loc.get("level") or ""
        ent, rdbg = resolve(name, name, "local", is_public=True, place_level=level, analysis_id=row.pk)
        if not ent.place_level and level:
            ent.place_level = level
            ent.save(update_fields=["place_level"])
        parent_name = (loc.get("parent") or "").strip()
        if parent_name and ent.parent_id is None and ent.status == "por_rever":
            parent, pdbg = resolve(parent_name, parent_name, "local", is_public=True, analysis_id=row.pk)
            if parent.pk != ent.pk:
                ent.parent = parent
                ent.save(update_fields=["parent"])
            rdbg["parent"] = pdbg
        link = links.get(ent.pk)
        if link:
            link.is_location = True
            link.debug["location"] = loc
            link.save(update_fields=["is_location", "debug"])
        else:
            links[ent.pk] = ArticleEntity.objects.create(
                analysis=row, entity=ent, name_in_text=name[:300], roles=[], is_location=True,
                debug={"resolution": rdbg, "location": loc},
            )
        dbg["locations"].append({"name": name, "level": level, "entity_id": ent.pk, "decision": rdbg.get("decision")})

    for s in output.get("sources") or []:
        stype = s.get("type") or "outro"
        name = (s.get("entity_name") or "").strip()
        ent, sdbg = None, {"decision": "sem entidade"}
        if name:
            ent = resolved.get(normalize(name))
            if ent is not None:
                sdbg = {"decision": "entidade desta análise", "entity_id": ent.pk}
            elif stype in ("outro_meio", "agencia"):
                ent, sdbg = resolve(name, name, "meio", is_public=True, analysis_id=row.pk)
            else:
                ent, sdbg = resolve(name, name, "outro", analysis_id=row.pk, create=False)
        CitedSource.objects.create(
            analysis=row, type=stype, name=name[:300], partial_attribute=(s.get("partial_attribute") or "")[:300],
            entity=ent, excerpt=s.get("excerpt") or "", debug={"resolution": sdbg, "llm": s},
        )
        dbg["sources"].append({"type": stype, "name": name, "entity_id": ent.pk if ent else None})

    seen_topics: dict[tuple, ArticleTopic] = {}
    for t in output.get("themes") or []:
        path = [p for p in t.get("path") or [] if p and p.strip()]
        if not path:
            dbg["themes"].append({"llm": t, "decision": "descartado: caminho vazio"})
            continue
        topic, created, tdbg = resolve_path(path, t.get("kind") or "tema", analysis_id=row.pk)
        edition = get_edition(topic, t.get("edition"))
        weight = min(1.0, max(0.0, float(t.get("weight") or 0.0)))
        key = (topic.pk, edition.pk if edition else None)
        tdbg.update(llm=t, weight_clamped=weight != t.get("weight"))
        if key in seen_topics:
            link = seen_topics[key]
            link.weight = max(link.weight, weight)
            link.debug.setdefault("merged", []).append(tdbg)
            link.save()
        else:
            seen_topics[key] = ArticleTopic.objects.create(
                analysis=row, topic=topic, edition=edition, weight=weight, created_topic=created, debug=tdbg)
        dbg["themes"].append({"path": path, "topic_id": topic.pk, "created": created,
                              "is_new_llm": t.get("is_new"), "edition": edition.label if edition else None})

    row.piece_type = output.get("piece_type") or ""
    row.piece_type_reasoning = llm_debug.get("reasoning") or ""
    row.ai_indicator = output.get("ai_indicator")
    row.usage = usage
    row.raw_response = output
    dbg["raw_text_chars"] = len(raw or "")
    row.debug = dbg
    row.status, row.finished_at, row.error = "done", timezone.now(), ""
    row.diff_from_previous = diff_from_previous(row)
    row.save()


def _score(value) -> float | None:
    try:
        return max(-1.0, min(1.0, float(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


def _reschedule(article) -> None:
    from crawl import scheduling

    article.refresh_from_db()
    scheduling.reschedule(article, timezone.now())
    article.save(update_fields=["next_revisit_at", "revisit_reason", "revisit_topic"])


# --- Diff entre análises ----------------------------------------------------------------------------------------

def previous_analysis(analysis: Analysis) -> Analysis | None:
    v = analysis.version
    return (Analysis.objects.filter(version__article_id=v.article_id, version__number__lt=v.number, status="done")
            .order_by("-version__number", "-finished_at").first())


def _snapshot(analysis: Analysis) -> dict:
    ents = {ae.entity_id: ae for ae in analysis.entities.select_related("entity")}
    return {
        "piece_type": analysis.piece_type,
        "entities": {k: {"name": ae.entity.canonical_name, "sentiment": ae.sentiment, "roles": ae.roles}
                     for k, ae in ents.items()},
        "topics": {(at.topic_id, at.edition_id): at.topic.name for at in analysis.topics.select_related("topic")},
        "sources": {(s.type, normalize(s.name or s.partial_attribute)) for s in analysis.sources.all()},
    }


def diff_from_previous(analysis: Analysis) -> dict | None:
    prev = previous_analysis(analysis)
    if prev is None:
        return None
    a, b = _snapshot(prev), _snapshot(analysis)
    common = set(a["entities"]) & set(b["entities"])
    out = {
        "previous_analysis": prev.pk,
        "previous_version": prev.version.number,
        "entities_added": [{"id": k, **b["entities"][k]} for k in sorted(set(b["entities"]) - set(a["entities"]))],
        "entities_removed": [{"id": k, **a["entities"][k]} for k in sorted(set(a["entities"]) - set(b["entities"]))],
        "sentiment_changed": [
            {"id": k, "name": b["entities"][k]["name"], "before": a["entities"][k]["sentiment"],
             "after": b["entities"][k]["sentiment"]}
            for k in sorted(common) if a["entities"][k]["sentiment"] != b["entities"][k]["sentiment"]
        ],
        "topics_added": [{"topic_id": k[0], "edition_id": k[1], "name": b["topics"][k]}
                         for k in sorted(set(b["topics"]) - set(a["topics"]), key=str)],
        "topics_removed": [{"topic_id": k[0], "edition_id": k[1], "name": a["topics"][k]}
                           for k in sorted(set(a["topics"]) - set(b["topics"]), key=str)],
        "sources_added": [{"type": t, "name": n} for t, n in sorted(b["sources"] - a["sources"])],
        "sources_removed": [{"type": t, "name": n} for t, n in sorted(a["sources"] - b["sources"])],
    }
    if a["piece_type"] != b["piece_type"]:
        out["piece_type"] = {"before": a["piece_type"], "after": b["piece_type"]}
    out["changed"] = any(v for k, v in out.items() if k not in ("previous_analysis", "previous_version"))
    return out


# --- Drain -----------------------------------------------------------------------------------------------------

def drain(inline: bool = False) -> int:
    """Retoma análises pendentes, adiadas pelo limite ou falhadas (com tentativas), as mais antigas primeiro.

    Por omissão põe-nas na fila `analysis`; `inline=True` corre-as já (testes, comandos). Respeita o orçamento:
    não põe na fila mais do que o que resta hoje. Devolve quantas retomou.
    """
    if not parameters.get("analysis.enabled"):
        return 0
    max_attempts = int(parameters.get("analysis.max_attempts"))
    stale = timezone.now() - timedelta(minutes=float(parameters.get("analysis.stale_running_min")))
    qs = (Analysis.objects
          .filter(Q(status__in=("pending", "skipped_budget")) | Q(status="failed", attempts__lt=max_attempts)
                  | Q(status="running", started_at__lt=stale))
          .order_by("created_at"))
    limit = min(int(parameters.get("analysis.drain_batch")), budget_left())
    version_ids = list(dict.fromkeys(qs.values_list("version_id", flat=True)[: max(limit, 0) * 2]))[:limit]
    if inline:
        for vid in version_ids:
            analyze(vid)
    else:
        from analysis.tasks import analyze_version

        for vid in version_ids:
            analyze_version.apply_async(args=[vid], queue="analysis")
    return len(version_ids)
