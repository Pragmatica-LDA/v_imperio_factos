"""Match dos temas devolvidos pelo LLM (`path` + `is_new`) com a árvore de temas da BD.

Regras:
- Percorre o caminho nível a nível: em cada nível procura, entre os filhos do tema anterior, um com o mesmo nome
  normalizado (sem acentos, minúsculas) ou o mesmo slug. Os temas fundidos seguem `merged_into`.
- A folha que não existe debaixo do pai indicado, mas existe uma única vez noutro ponto da árvore, liga a esse
  tema (o LLM às vezes encurta ou troca o ramo). Os níveis intermédios não têm este atalho.
- O que falta cria-se no estado `por_rever` (pais incluídos), com o debug da análise que o criou.
- `is_new` do LLM é só uma pista: se o caminho já existe, liga; se diz que existe e não existe, cria.
"""

from __future__ import annotations

from django.utils.text import slugify

from entities.normalize import normalize
from topics.models import Edition, Topic


def final_topic(topic: Topic) -> Topic:
    seen = set()
    while topic.merged_into_id and topic.pk not in seen:
        seen.add(topic.pk)
        topic = topic.merged_into
    return topic


def _child(parent: Topic | None, name: str) -> Topic | None:
    key, slug = normalize(name), slugify(name)
    for t in Topic.objects.filter(parent=parent).select_related("merged_into"):
        if normalize(t.name) == key or t.slug == slug:
            return final_topic(t)
    return None


def _unique_slug(base: str) -> str:
    base = (base or "tema")[:280]
    slug, n = base, 2
    while Topic.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def resolve_path(path: list[str], kind: str, analysis_id: int | None = None,
                 allow_elsewhere: bool = True) -> tuple[Topic, bool, dict]:
    """(tema-folha, criado, debug)."""
    path = [p.strip() for p in path if p and p.strip()]
    if not path:
        raise ValueError("caminho de tema vazio")
    debug: dict = {"path": path, "steps": []}
    parent: Topic | None = None
    created_any = False
    for i, name in enumerate(path):
        leaf = i == len(path) - 1
        found = _child(parent, name)
        if found is None and leaf and allow_elsewhere:
            elsewhere = [final_topic(t) for t in Topic.objects.filter(name__iexact=name).select_related("merged_into")]
            elsewhere = [t for t in elsewhere if t.status != "merged"]
            elsewhere = list({t.pk: t for t in elsewhere}.values())
            if len(elsewhere) == 1:
                found = elsewhere[0]
                debug["steps"].append({"name": name, "match": "folha noutro ramo", "topic_id": found.pk})
            elif len(elsewhere) > 1:
                debug["steps"].append({"name": name, "match": "folha ambígua noutros ramos",
                                       "candidates": [t.pk for t in elsewhere]})
        elif found is not None:
            debug["steps"].append({"name": name, "match": "existente", "topic_id": found.pk})
        if found is None:
            slug_base = slugify(" ".join(path[: i + 1]))
            found = Topic.objects.create(
                name=name[:300], slug=_unique_slug(slug_base), parent=parent,
                kind=kind if leaf and kind in {k for k, _ in Topic.KIND_CHOICES} else "tema",
                status="por_rever", debug={"created_by_analysis": analysis_id, "path": path[: i + 1]},
            )
            created_any = created_any or leaf
            debug["steps"].append({"name": name, "match": "criado por rever", "topic_id": found.pk})
        parent = found
    return parent, created_any, debug


def get_edition(topic: Topic, label: str | None) -> Edition | None:
    label = (label or "").strip()[:100]
    if not label:
        return None
    for ed in topic.editions.all():   # match normalizado ("OE 2027" == "oe 2027")
        if normalize(ed.label) == normalize(label):
            return ed
    return Edition.objects.get_or_create(topic=topic, label=label)[0]
