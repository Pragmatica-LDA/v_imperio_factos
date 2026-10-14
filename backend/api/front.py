"""Front-office (/api/front/): o que está a acontecer, histórias, entidades em destaque, detalhe e arquivo.

Só leitura. A unidade principal é a **história**: notícias da janela `front.window_h` agrupadas por cluster de
duplicados ou por entidades salientes partilhadas (`front.story_min_shared`). Cada notícia usa só a última análise
feita da sua versão mais recente.

Indicadores derivados (a análise não tem sentimento global da notícia):
- **tom** da notícia = média do sentimento por entidade (sem locais); positivo/negativo acima de `front.tone_threshold`.
- **com IA** = indicador de IA ≥ `front.ai_threshold` (é um indicador, nunca um facto).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Avg, Case, Count, FloatField, Q, Value, When
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from analysis.models import Analysis, CitedSource
from core import parameters
from crawl.models import Article, HomepageAppearance, Version
from duplicates.models import ClusterMember
from entities.models import ArticleEntity, Entity
from sources.models import Site
from topics.models import ArticleTopic, Topic, TopicTemperature

SENTIMENT_VALUE = Case(When(sentiment="positivo", then=Value(1.0)), When(sentiment="negativo", then=Value(-1.0)),
                       default=Value(0.0), output_field=FloatField())


def P(key):
    return parameters.get(key)


def _t(article) -> object:
    return article.published_at or article.first_seen_at


def _active_articles():
    return (Article.objects.filter(status="active").select_related("site")
            .annotate(t=Coalesce("published_at", "first_seen_at")))


def latest_analyses(article_ids) -> dict[int, int]:
    """article_id → id da última análise feita (versão mais recente com análise 'done')."""
    if not article_ids:
        return {}
    rows = (Analysis.objects.filter(status="done", version__article_id__in=list(article_ids))
            .order_by("version__article_id", "-version__number", "-created_at")
            .distinct("version__article_id").values_list("version__article_id", "id"))
    return dict(rows)


def tone_of(avg: float | None) -> str | None:
    if avg is None:
        return None
    th = float(P("front.tone_threshold"))
    return "positivo" if avg >= th else "negativo" if avg <= -th else "neutro"


def ai_flag(ai: dict | None) -> bool | None:
    score = (ai or {}).get("score")
    if score is None:
        return None
    return float(score) >= float(P("front.ai_threshold"))


def _mention_q():
    """Menções que contam para o destaque: sem locais, sem papéis só excluídos, tipos não excluídos."""
    return Q(is_location=False) & ~Q(entity__type__in=list(P("front.entity_exclude_types")))


def _salient(mentions) -> set[int]:
    types = set(P("front.story_entity_types"))
    excl = set(P("front.entity_exclude_roles"))
    return {m["entity_id"] for m in mentions
            if not m["is_location"] and m["entity__type"] in types
            and not (m["roles"] and set(m["roles"]) <= excl)}


# Enriquecimento em lote -----------------------------------------------------------------------------------------

def enrich(articles: list, with_entities: bool = False) -> list[dict]:
    """Cartões de notícia: título, meio, data, resumo, tom, IA, temas, tamanho do cluster (queries em lote)."""
    ids = [a.pk for a in articles]
    latest = latest_analyses(ids)
    aids = list(latest.values())
    an = {a["id"]: a for a in Analysis.objects.filter(id__in=aids).values("id", "summary", "piece_type",
                                                                          "ai_indicator")}
    tones = dict(ArticleEntity.objects.filter(analysis_id__in=aids, is_location=False).exclude(sentiment="")
                 .values("analysis_id").annotate(avg=Avg(Coalesce("sentiment_score", SENTIMENT_VALUE)))
                 .values_list("analysis_id", "avg"))
    topics: dict[int, list] = defaultdict(list)
    for r in (ArticleTopic.objects.filter(analysis_id__in=aids).exclude(topic__status="merged")
              .order_by("-weight").values("analysis_id", "topic_id", "topic__name", "weight")):
        topics[r["analysis_id"]].append({"id": r["topic_id"], "name": r["topic__name"], "weight": r["weight"]})
    clusters = {m["article_id"]: m for m in ClusterMember.objects.filter(article_id__in=ids)
                .annotate(size=Count("cluster__members")).values("article_id", "cluster_id", "size", "is_original")}
    ents: dict[int, list] = defaultdict(list)
    if with_entities:
        for r in (ArticleEntity.objects.filter(analysis_id__in=aids).filter(_mention_q())
                  .values("analysis_id", "entity_id", "entity__canonical_name", "entity__type", "sentiment")):
            ents[r["analysis_id"]].append({"id": r["entity_id"], "name": r["entity__canonical_name"],
                                           "type": r["entity__type"], "sentiment": r["sentiment"]})
    out = []
    for a in articles:
        aid = latest.get(a.pk)
        x = an.get(aid, {})
        avg = tones.get(aid)
        c = clusters.get(a.pk)
        card = {
            "id": a.pk, "title": a.title, "site": a.site.slug, "site_name": a.site.name,
            "url": a.canonical_url, "published_at": _t(a), "section": a.section,
            "piece_type": x.get("piece_type") or a.piece_type, "summary": x.get("summary", ""),
            "analysed": aid is not None, "tone": tone_of(avg), "tone_avg": round(avg, 3) if avg is not None else None,
            "ai_score": (x.get("ai_indicator") or {}).get("score"), "ai": ai_flag(x.get("ai_indicator")),
            "topics": topics.get(aid, [])[:3], "version_count": a.version_count,
            "cluster": {"id": c["cluster_id"], "size": c["size"], "is_original": c["is_original"]} if c else None,
        }
        if with_entities:
            card["entities"] = ents.get(aid, [])[:8]
        out.append(card)
    return out


# Histórias ------------------------------------------------------------------------------------------------------

def build_stories(now, window_h: float) -> list[dict]:
    """Agrupa as notícias da janela em histórias e ordena-as (actualidade × cobertura × temperatura × destaque)."""
    since = now - timedelta(hours=window_h)
    arts = list(_active_articles().filter(t__gte=since, t__lte=now + timedelta(hours=1))
                .order_by("-t")[: int(P("front.max_window_articles"))])
    if not arts:
        return []
    by_id = {a.pk: a for a in arts}
    latest = latest_analyses(by_id)
    mentions: dict[int, list] = defaultdict(list)
    for m in (ArticleEntity.objects.filter(analysis_id__in=latest.values())
              .values("analysis_id", "entity_id", "entity__type", "roles", "is_location")):
        mentions[m["analysis_id"]].append(m)
    salient = {art: _salient(mentions.get(an, [])) for art, an in latest.items()}

    # Vizinhos: mesmo cluster de duplicados ou ≥ k entidades salientes partilhadas.
    k = int(P("front.story_min_shared"))
    index: dict[int, list[int]] = defaultdict(list)
    for art, es in salient.items():
        for e in es:
            index[e].append(art)
    shared: Counter = Counter()
    for arts_e in index.values():
        for i, a in enumerate(arts_e):
            for b in arts_e[i + 1:]:
                shared[(a, b) if a < b else (b, a)] += 1
    # Peso de cada entidade na janela (IDF): "Governo" ou "PSP" em dezenas de notícias pesam pouco.
    n_docs = max(len(salient), 1)
    idf = {e: math.log(1 + n_docs / len(arts_e)) for e, arts_e in index.items()}
    mass = {a: sum(idf[e] for e in es) for a, es in salient.items()}
    min_sim = float(P("front.story_min_similarity"))
    neighbours: dict[int, set] = defaultdict(set)
    for (a, b), n in shared.items():
        if n < k:
            continue
        common = sum(idf[e] for e in salient[a] & salient[b])
        if common / max(min(mass[a], mass[b]), 1e-9) >= min_sim:
            neighbours[a].add(b)
            neighbours[b].add(a)
    cl = dict(ClusterMember.objects.filter(article_id__in=by_id).values_list("article_id", "cluster_id"))
    by_cluster: dict[int, list] = defaultdict(list)
    for a, c in cl.items():
        by_cluster[c].append(a)
    for members in by_cluster.values():
        for a in members:
            neighbours[a].update(m for m in members if m != a)

    # Pontuação base de cada notícia.
    temps: dict[int, float] = defaultdict(float)
    for r in (ArticleTopic.objects.filter(analysis_id__in=latest.values(), topic__status="active")
              .values("analysis_id", "topic__temperature")):
        temps[r["analysis_id"]] = max(temps[r["analysis_id"]], r["topic__temperature"] or 0)
    max_temp = max(temps.values(), default=0) or 1.0
    on_home = set(HomepageAppearance.objects.filter(article_id__in=by_id).values_list("article_id", flat=True))
    half = float(P("front.story_half_life_h"))
    w_cov, w_temp = float(P("front.story_weight_coverage")), float(P("front.story_weight_temperature"))
    w_home = float(P("front.story_weight_homepage"))

    def score(a) -> float:
        age_h = max((now - _t(by_id[a])).total_seconds() / 3600, 0)
        temp = temps.get(latest.get(a), 0) / max_temp
        return (0.5 ** (age_h / half) * (1 + w_cov * len(neighbours[a])) * (1 + w_temp * temp)
                * (1 + (w_home if a in on_home else 0)))

    scores = {a: score(a) for a in by_id}
    assigned: set[int] = set()
    stories = []
    for lead in sorted(by_id, key=lambda a: (latest.get(a) is None, -scores[a])):
        if lead in assigned:
            continue
        members = [lead] + sorted((n for n in neighbours[lead] if n not in assigned), key=lambda n: -scores[n])
        assigned.update(members)
        stories.append({"lead": lead, "members": members, "score": scores[lead]})
        if len(stories) >= int(P("front.stories_limit")):
            break

    cards = {c["id"]: c for c in enrich([by_id[a] for s in stories for a in s["members"]], with_entities=True)}
    out = []
    for s in stories:
        members = [cards[a] for a in s["members"]]
        lead_ents = salient.get(s["lead"], set())
        common = Counter(e for a in s["members"][1:] for e in salient.get(a, set()) & lead_ents)
        names = {e["id"]: e["name"] for e in cards[s["lead"]].get("entities", [])}
        out.append({
            "score": round(s["score"], 4),
            "lead": cards[s["lead"]],
            "others": [{k: c[k] for k in ("id", "title", "site", "site_name", "published_at", "url", "tone", "ai")}
                       for c in members[1:]],
            "n_articles": len(members),
            "sites": sorted({c["site"] for c in members}),
            "shared_entities": [{"id": e, "name": names[e]} for e, _ in common.most_common(5) if e in names],
            "on_homepage": s["lead"] in on_home,
        })
    return out


# Entidades em destaque ------------------------------------------------------------------------------------------

def trending_entities(now, window_h: float, places: bool = False) -> list[dict]:
    """Entidades (ou locais) com mais notícias na janela, com a variação face à janela anterior."""
    since, prev = now - timedelta(hours=window_h), now - timedelta(hours=2 * window_h)
    arts = dict(_active_articles().filter(t__gte=prev, t__lte=now + timedelta(hours=1))
                .values_list("pk", "t"))
    latest = latest_analyses(arts)
    an_to_art = {v: k for k, v in latest.items()}
    qs = ArticleEntity.objects.filter(analysis_id__in=an_to_art)
    if places:
        qs = qs.filter(Q(is_location=True) | Q(entity__type="local"))
    else:
        qs = qs.filter(_mention_q()).exclude(entity__type="local")
    excl = set(P("front.entity_exclude_roles"))
    cur: dict[int, dict] = {}
    prev_n: Counter = Counter()
    site_of = dict(Article.objects.filter(pk__in=arts).values_list("pk", "site__slug"))
    for m in qs.values("analysis_id", "entity_id", "entity__canonical_name", "entity__type", "sentiment", "roles"):
        if m["roles"] and set(m["roles"]) <= excl:
            continue
        art = an_to_art[m["analysis_id"]]
        if arts[art] < since:
            prev_n[(m["entity_id"], art)] = 1
            continue
        e = cur.setdefault(m["entity_id"], {
            "id": m["entity_id"], "name": m["entity__canonical_name"], "type": m["entity__type"],
            "articles": set(), "sites": set(), "sentiment": Counter()})
        e["articles"].add(art)
        e["sites"].add(site_of.get(art))
        if m["sentiment"]:
            e["sentiment"][m["sentiment"]] += 1
    prev_count = Counter(e for e, _ in prev_n)
    rows = []
    for e in cur.values():
        n = len(e["articles"])
        rows.append({"id": e["id"], "name": e["name"], "type": e["type"], "n_articles": n,
                     "n_sites": len(e["sites"]), "sites": sorted(s for s in e["sites"] if s),
                     "prev_articles": prev_count.get(e["id"], 0), "delta": n - prev_count.get(e["id"], 0),
                     "sentiment": {k: e["sentiment"].get(k, 0) for k in ("positivo", "neutro", "negativo")}})
    rows.sort(key=lambda r: (-r["n_articles"], -r["n_sites"], -r["delta"], r["name"]))
    return rows[: int(P("front.places_limit" if places else "front.entity_limit"))]


# Estatísticas ---------------------------------------------------------------------------------------------------

def compute_stats(now) -> dict:
    """Tom, IA e tipo de peça (arquivo todo e por meio) + série diária de notícias por meio."""
    arts = dict(Article.objects.filter(status="active").values_list("pk", "site__slug"))
    latest = latest_analyses(arts)
    an_to_art = {v: k for k, v in latest.items()}
    avgs = dict(ArticleEntity.objects.filter(analysis_id__in=an_to_art, is_location=False).exclude(sentiment="")
                .values("analysis_id").annotate(avg=Avg(Coalesce("sentiment_score", SENTIMENT_VALUE)))
                .values_list("analysis_id", "avg"))
    blank = lambda: {"n": 0, "analysed": 0, "tone": Counter(), "ai": Counter(), "piece_type": Counter()}  # noqa: E731
    total, by_site = blank(), defaultdict(blank)
    for site in arts.values():
        for b in (total, by_site[site]):
            b["n"] += 1
    for a in Analysis.objects.filter(id__in=an_to_art).values("id", "piece_type", "ai_indicator"):
        site = arts[an_to_art[a["id"]]]
        tone = tone_of(avgs.get(a["id"])) or "sem_entidades"
        flag = ai_flag(a["ai_indicator"])
        ai = "sem_dados" if flag is None else "com_ia" if flag else "sem_ia"
        for b in (total, by_site[site]):
            b["analysed"] += 1
            b["tone"][tone] += 1
            b["ai"][ai] += 1
            b["piece_type"][a["piece_type"] or "desconhecido"] += 1

    days = int(P("stats.daily_days"))
    start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    daily: dict[str, Counter] = defaultdict(Counter)
    for r in (_active_articles().filter(t__gte=start).annotate(d=TruncDate("t")).values("d", "site__slug")
              .annotate(n=Count("id")).order_by()):
        daily[r["d"].isoformat()][r["site__slug"]] = r["n"]
    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).date().isoformat()
        series.append({"date": d, "total": sum(daily[d].values()), "by_site": dict(daily[d])})

    plain = lambda b: {**b, "tone": dict(b["tone"]), "ai": dict(b["ai"]), "piece_type": dict(b["piece_type"])}  # noqa: E731
    return {"total": plain(total), "by_site": {k: plain(v) for k, v in by_site.items()}, "daily": series,
            "thresholds": {"tone": float(P("front.tone_threshold")), "ai": float(P("front.ai_threshold"))}}


def hot_topics(now) -> list[dict]:
    limit = int(P("front.hot_topics_limit"))
    window = float(P("topics.window_h"))
    topics = list(Topic.objects.filter(status="active", temperature__gt=0).select_related("parent")
                  .order_by("-temperature")[:limit])
    hist: dict[int, list] = defaultdict(list)
    for r in (TopicTemperature.objects.filter(topic__in=topics, at__gte=now - timedelta(hours=window))
              .order_by("at").values("topic_id", "at", "value", "articles", "sites")):
        hist[r["topic_id"]].append({"at": r["at"], "value": round(r["value"], 3)})
    since = now - timedelta(hours=float(P("front.window_h")))
    arts = dict(_active_articles().filter(t__gte=now - timedelta(hours=window)).values_list("pk", "t"))
    latest = latest_analyses(arts)
    an_to_art = {v: k for k, v in latest.items()}
    per_topic: dict[int, set] = defaultdict(set)
    for tid, an in ArticleTopic.objects.filter(topic__in=topics, analysis_id__in=an_to_art).values_list(
            "topic_id", "analysis_id"):
        per_topic[tid].add(an_to_art[an])
    recent_ids = {a for t in topics for a in sorted(per_topic[t.pk], key=lambda a: arts[a], reverse=True)[:3]}
    cards = {c["id"]: c for c in enrich(list(_active_articles().filter(pk__in=recent_ids)))}
    site_of = dict(Article.objects.filter(pk__in={a for s in per_topic.values() for a in s})
                   .values_list("pk", "site__slug"))
    out = []
    for t in topics:
        ids = sorted(per_topic[t.pk], key=lambda a: arts[a], reverse=True)
        out.append({
            "id": t.pk, "name": t.name, "slug": t.slug, "kind": t.kind,
            "parent": {"id": t.parent_id, "name": t.parent.name} if t.parent_id else None,
            "temperature": round(t.temperature, 3), "hot": t.temperature >= float(P("topics.hot_threshold")),
            "n_articles": len(ids), "n_articles_now": sum(1 for a in ids if arts[a] >= since),
            "sites": sorted({site_of[a] for a in ids if a in site_of}), "history": hist.get(t.pk, []),
            "articles": [cards[a] for a in ids[:3] if a in cards],
        })
    return out


def compute_overview(now) -> dict:
    window = float(P("front.window_h"))
    since = now - timedelta(hours=window)
    recent = _active_articles().filter(t__gte=since, t__lte=now + timedelta(hours=1))
    per_site = int(P("front.latest_per_site"))
    latest_by_site = []
    for site in Site.objects.filter(active=True).order_by("name"):
        arts = list(_active_articles().filter(site=site).order_by("-t")[:per_site])
        latest_by_site.append({"site": site.slug, "name": site.name, "articles": enrich(arts)})
    return {
        "generated_at": now, "window_h": window,
        "totals": {
            "articles_window": recent.count(),
            "sites_window": recent.values("site").distinct().count(),
            "articles_total": Article.objects.filter(status="active").count(),
            "analysed_total": Analysis.objects.filter(status="done").values("version__article").distinct().count(),
            "entities_total": Entity.objects.exclude(status="merged").count(),
            "topics_active": Topic.objects.filter(status="active").count(),
            "versions_window": Version.objects.filter(created_at__gte=since, number__gt=1).count(),
        },
        "stories": build_stories(now, window),
        "hot_topics": hot_topics(now),
        "entities": trending_entities(now, window),
        "places": trending_entities(now, window, places=True),
        "latest_by_site": latest_by_site,
        "stats": compute_stats(now),
    }


class LoginView(ObtainAuthToken):
    """Utilizador + password → token DRF. Sem autenticação por sessão: uma sessão aberta no admin (os cookies de
    localhost são partilhados entre portas) faria o DRF exigir CSRF e o login falhava com 403."""

    authentication_classes: list = []


OVERVIEW_KEY = "api:front:overview"


def warm_overview() -> dict:
    """Calcula e guarda o overview. A tarefa periódica guarda-o pelo dobro do TTL, para nunca expirar entre corridas."""
    from api.mixins import to_json

    data = to_json(compute_overview(timezone.now()))
    cache.set(OVERVIEW_KEY, data, 2 * int(P("cache.front_s")))
    return data


class OverviewView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Tudo o que a homepage do front-office precisa (pré-calculado pela tarefa `api.tasks.warm_front_overview`)."""
        data = cache.get(OVERVIEW_KEY)
        if data is None:
            data = warm_overview()
        return Response(data)


# Arquivo --------------------------------------------------------------------------------------------------------

class ArticlesView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT, parameters=[
        OpenApiParameter(n, t) for n, t in (("q", OpenApiTypes.STR), ("site", OpenApiTypes.STR),
                                            ("topic", OpenApiTypes.INT), ("entity", OpenApiTypes.INT),
                                            ("piece_type", OpenApiTypes.STR), ("since", OpenApiTypes.DATE),
                                            ("until", OpenApiTypes.DATE), ("limit", OpenApiTypes.INT),
                                            ("offset", OpenApiTypes.INT))])
    def get(self, request):
        """Arquivo pesquisável de notícias, com tom, IA e temas de cada uma."""
        qp = request.query_params
        qs = _active_articles()
        if qp.get("q"):
            qs = qs.filter(title__icontains=qp["q"].strip())
        if qp.get("site"):
            qs = qs.filter(site__slug=qp["site"])
        for key, field in (("topic", "versions__analyses__topics__topic"),
                           ("entity", "versions__analyses__entities__entity")):
            if qp.get(key):
                try:
                    qs = qs.filter(**{field: int(qp[key])})
                except ValueError as exc:
                    raise ValidationError({key: "Tem de ser um id."}) from exc
        if qp.get("piece_type"):
            qs = qs.filter(versions__analyses__piece_type=qp["piece_type"], versions__analyses__status="done")
        if qp.get("since"):
            qs = qs.filter(t__date__gte=qp["since"])
        if qp.get("until"):
            qs = qs.filter(t__date__lte=qp["until"])
        qs = qs.distinct().order_by("-t", "-id")
        pager = LimitOffsetPagination()
        page = pager.paginate_queryset(qs, request, view=self)
        return pager.get_paginated_response(enrich(page, with_entities=True))


# Detalhe da notícia ---------------------------------------------------------------------------------------------

def _idf(entity_ids) -> dict[int, float]:
    n_total = max(Analysis.objects.filter(status="done").values("version__article").distinct().count(), 1)
    df = dict(ArticleEntity.objects.filter(entity_id__in=entity_ids).values("entity_id")
              .annotate(n=Count("analysis__version__article", distinct=True)).values_list("entity_id", "n"))
    return {e: math.log(1 + n_total / max(df.get(e, 1), 1)) for e in entity_ids}


def related_articles(article, analysis_id: int | None, exclude: set[int]) -> dict:
    """Notícias do mesmo tema e notícias de outros temas com as mesmas entidades (pesadas pelo IDF)."""
    limit = int(P("front.related_limit"))
    if analysis_id is None:
        return {"same_topic": [], "other_topics": []}
    mine = list(ArticleEntity.objects.filter(analysis_id=analysis_id)
                .values("entity_id", "entity__type", "roles", "is_location"))
    ents = _salient(mine)
    my_topics = set(ArticleTopic.objects.filter(analysis_id=analysis_id).values_list("topic_id", flat=True))
    idf = _idf(ents)
    cand: dict[int, set] = defaultdict(set)
    an_of: dict[int, set] = defaultdict(set)
    for art, an, e in (ArticleEntity.objects.filter(entity_id__in=ents, analysis__status="done",
                                                    analysis__version__article__status="active")
                       .exclude(analysis__version__article=article)
                       .values_list("analysis__version__article_id", "analysis_id", "entity_id")):
        if art not in exclude:
            cand[art].add(e)
            an_of[art].add(an)
    latest = latest_analyses(cand)
    scored = {a: sum(idf[e] for e in es) for a, es in cand.items() if latest.get(a) in an_of[a]}
    topics_of: dict[int, set] = defaultdict(set)
    for an, tid in ArticleTopic.objects.filter(analysis_id__in=[latest[a] for a in scored]).values_list(
            "analysis_id", "topic_id"):
        topics_of[an].add(tid)
    min_shared = int(P("front.story_min_shared"))
    same = [a for a in scored if topics_of[latest[a]] & my_topics]
    other = [a for a in scored if not topics_of[latest[a]] & my_topics and len(cand[a]) >= min_shared]
    # Mesmo tema sem entidades em comum: completa com as mais recentes do tema.
    if len(same) < limit and my_topics:
        extra = (ArticleTopic.objects.filter(topic_id__in=my_topics, analysis__status="done",
                                             analysis__version__article__status="active")
                 .exclude(analysis__version__article=article)
                 .exclude(analysis__version__article__in=exclude | set(same))
                 .order_by("-analysis__version__article__published_at")
                 .values_list("analysis__version__article_id", flat=True).distinct()[: limit * 3])
        for a in extra:
            if a not in same:
                same.append(a)
                scored.setdefault(a, 0.0)

    by_id = {a.pk: a for a in _active_articles().filter(pk__in=set(same) | set(other))}
    names = dict(Entity.objects.filter(pk__in=ents).values_list("pk", "canonical_name"))

    def top(ids):
        ids = sorted((a for a in ids if a in by_id), key=lambda a: (-scored[a], -_t(by_id[a]).timestamp()))[:limit]
        cards = {c["id"]: c for c in enrich([by_id[a] for a in ids])}
        return [{**cards[a], "similarity": round(scored[a], 3),
                 "shared_entities": [{"id": e, "name": names.get(e, "")} for e in
                                     sorted(cand.get(a, ()), key=lambda e: -idf[e])]} for a in ids]

    return {"same_topic": top(same), "other_topics": top(other)}


class ArticleDetailView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk: int):
        """Notícia com análise (entidades, temas, fontes), versões, duplicados e notícias relacionadas."""
        article = get_object_or_404(Article.objects.select_related("site")
                                    .annotate(t=Coalesce("published_at", "first_seen_at")), pk=pk)
        card = enrich([article])[0]
        an_id = latest_analyses([article.pk]).get(article.pk)
        an = Analysis.objects.filter(pk=an_id).select_related("version").first()
        version = article.versions.order_by("-number").first()
        entities, topics, sources = [], [], []
        if an:
            for m in (ArticleEntity.objects.filter(analysis=an).select_related("entity")
                      .order_by("is_location", "entity__type", "entity__canonical_name")):
                entities.append({"id": m.entity_id, "name": m.entity.canonical_name, "type": m.entity.type,
                                 "name_in_text": m.name_in_text, "roles": m.roles, "position": m.position_at_time,
                                 "sentiment": m.sentiment, "sentiment_score": m.sentiment_score,
                                 "evidence": m.evidence, "is_location": m.is_location})
            for t in ArticleTopic.objects.filter(analysis=an).select_related("topic", "topic__parent", "edition") \
                    .order_by("-weight"):
                topics.append({"id": t.topic_id, "name": t.topic.name, "weight": t.weight,
                               "parent": t.topic.parent.name if t.topic.parent_id else None,
                               "edition": t.edition.label if t.edition_id else None,
                               "temperature": round(t.topic.temperature, 3)})
            sources = list(CitedSource.objects.filter(analysis=an)
                           .values("type", "name", "partial_attribute", "excerpt", "entity_id"))
        cluster = []
        m = ClusterMember.objects.filter(article=article).select_related("cluster").first()
        if m:
            mates = {x.article_id: x for x in ClusterMember.objects.filter(cluster=m.cluster)
                     .exclude(article=article)}
            for c in enrich(list(_active_articles().filter(pk__in=mates))):
                cluster.append({**c, "similarity": mates[c["id"]].similarity,
                                "is_original": mates[c["id"]].is_original})
        content = version.content if version else {}
        return Response({
            **card,
            "lead": content.get("lead") or content.get("subtitle") or "",
            "authors": content.get("authors") or [],
            "text": version.text if version else "",
            "word_count": version.word_count if version else 0,
            "analysis": {"id": an.pk, "model": an.model, "prompt_version": an.prompt_version,
                         "version_number": an.version.number, "piece_type_reasoning": an.piece_type_reasoning,
                         "ai_indicator": an.ai_indicator, "debug": an.debug} if an else None,
            "entities": entities, "topics_full": topics, "sources": sources,
            "versions": list(article.versions.order_by("number").values("number", "created_at", "change_ratio",
                                                                       "word_count")),
            "duplicates": cluster,
            "related": related_articles(article, an_id, {c["id"] for c in cluster}),
        })


# Entidade e tema ------------------------------------------------------------------------------------------------

def _series(art_times: dict[int, object], days: int, now) -> list[dict]:
    start = timezone.localtime(now).date() - timedelta(days=days - 1)
    cnt = Counter(timezone.localtime(t).date() for t in art_times.values() if t)
    return [{"date": (start + timedelta(days=i)).isoformat(), "n": cnt.get(start + timedelta(days=i), 0)}
            for i in range(days)]


def _articles_of(analysis_filter: Q) -> tuple[dict[int, int], dict]:
    """(article_id → análise usada, artigos) das notícias activas cuja última análise cumpre o filtro."""
    rows = (Analysis.objects.filter(analysis_filter, status="done", version__article__status="active")
            .values_list("version__article_id", "id"))
    cand: dict[int, set] = defaultdict(set)
    for art, an in rows:
        cand[art].add(an)
    latest = latest_analyses(cand)
    keep = {a: latest[a] for a in cand if latest.get(a) in cand[a]}
    arts = {a.pk: a for a in _active_articles().filter(pk__in=keep)}
    return keep, arts


class EntityDetailView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk: int):
        """Entidade: menções ao longo do tempo, sentimento, papéis, entidades e temas associados, notícias."""
        e = get_object_or_404(Entity.objects.prefetch_related("aliases"), pk=pk)
        now = timezone.now()
        keep, arts = _articles_of(Q(entities__entity=e))
        mentions = list(ArticleEntity.objects.filter(entity=e, analysis_id__in=keep.values())
                        .values("analysis_id", "sentiment", "roles", "position_at_time"))
        sent_of = {m["analysis_id"]: m["sentiment"] for m in mentions}
        roles = Counter(r for m in mentions for r in (m["roles"] or []))
        positions = Counter(m["position_at_time"] for m in mentions if m["position_at_time"])
        co = Counter()
        co_names = {}
        for r in (ArticleEntity.objects.filter(analysis_id__in=keep.values()).filter(_mention_q())
                  .exclude(entity=e).values("entity_id", "entity__canonical_name", "entity__type", "analysis_id")
                  .distinct()):
            co[r["entity_id"]] += 1
            co_names[r["entity_id"]] = (r["entity__canonical_name"], r["entity__type"])
        topics = Counter()
        tnames = {}
        for tid, name in ArticleTopic.objects.filter(analysis_id__in=keep.values()).values_list(
                "topic_id", "topic__name"):
            topics[tid] += 1
            tnames[tid] = name
        recent = sorted(arts.values(), key=lambda a: _t(a), reverse=True)[:60]
        cards = enrich(recent)
        for c in cards:
            c["entity_sentiment"] = sent_of.get(keep.get(c["id"]))
        sites = Counter(a.site.slug for a in arts.values())
        return Response({
            "id": e.pk, "name": e.canonical_name, "type": e.type, "status": e.status, "is_public": e.is_public,
            "external_id": e.external_id, "description": e.description, "merged_into": e.merged_into_id,
            "aliases": sorted({a.alias for a in e.aliases.all()} - {e.canonical_name}),
            "n_articles": len(arts), "sites": dict(sites),
            "sentiment": {k: sum(1 for m in mentions if m["sentiment"] == k)
                          for k in ("positivo", "neutro", "negativo")},
            "roles": dict(roles.most_common()), "positions": [p for p, _ in positions.most_common(5)],
            "series": _series({a: _t(x) for a, x in arts.items()}, int(P("front.entity_days")), now),
            "co_entities": [{"id": i, "name": co_names[i][0], "type": co_names[i][1], "n": n}
                            for i, n in co.most_common(20)],
            "topics": [{"id": i, "name": tnames[i], "n": n} for i, n in topics.most_common(12)],
            "articles": cards,
        })


class TopicDetailView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk: int):
        """Tema: caminho, subtemas, temperatura ao longo do tempo, notícias, entidades e meios."""
        t = get_object_or_404(Topic.objects.select_related("parent"), pk=pk)
        now = timezone.now()
        ids, frontier = {t.pk}, [t.pk]
        while frontier:   # inclui os subtemas
            frontier = list(Topic.objects.filter(parent_id__in=frontier).exclude(pk__in=ids)
                            .values_list("pk", flat=True))
            ids.update(frontier)
        keep, arts = _articles_of(Q(topics__topic_id__in=ids))
        path, p = [], t.parent
        while p is not None and len(path) < 10:
            path.insert(0, {"id": p.pk, "name": p.name})
            p = p.parent
        ents = Counter()
        enames = {}
        for r in (ArticleEntity.objects.filter(analysis_id__in=keep.values()).filter(_mention_q())
                  .exclude(entity__type="local").values("entity_id", "entity__canonical_name", "entity__type",
                                                         "analysis_id").distinct()):
            ents[r["entity_id"]] += 1
            enames[r["entity_id"]] = (r["entity__canonical_name"], r["entity__type"])
        hist = list(TopicTemperature.objects.filter(topic=t, at__gte=now - timedelta(days=int(P("front.entity_days"))))
                    .order_by("at").values("at", "value", "articles", "sites"))
        recent = sorted(arts.values(), key=lambda a: _t(a), reverse=True)[:60]
        return Response({
            "id": t.pk, "name": t.name, "kind": t.kind, "status": t.status, "description": t.description,
            "recurrence": t.recurrence, "temperature": round(t.temperature, 3),
            "hot": t.temperature >= float(P("topics.hot_threshold")), "path": path,
            "children": list(t.children.exclude(status="merged").order_by("-temperature")
                             .values("id", "name", "temperature")),
            "editions": list(t.editions.order_by("starts_at", "label").values("id", "label", "temperature")),
            "n_articles": len(arts), "sites": dict(Counter(a.site.slug for a in arts.values())),
            "history": hist, "series": _series({a: _t(x) for a, x in arts.items()}, int(P("front.entity_days")), now),
            "entities": [{"id": i, "name": enames[i][0], "type": enames[i][1], "n": n}
                         for i, n in ents.most_common(20)],
            "articles": enrich(recent),
        })


class SearchView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT, parameters=[OpenApiParameter("q", OpenApiTypes.STR)])
    def get(self, request):
        """Pesquisa rápida para o front-office: entidades (nome e aliases), temas e títulos."""
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"entities": [], "topics": [], "articles": []})
        ents = (Entity.objects.exclude(status="merged")
                .filter(Q(canonical_name__icontains=q) | Q(aliases__alias__icontains=q)).distinct()
                .annotate(n=Count("mentions", distinct=True)).order_by("-n")[:8])
        topics = Topic.objects.exclude(status="merged").filter(name__icontains=q).order_by("-temperature")[:6]
        arts = list(_active_articles().filter(title__icontains=q).order_by("-t")[:8])
        return Response({
            "entities": [{"id": e.pk, "name": e.canonical_name, "type": e.type, "n": e.n} for e in ents],
            "topics": [{"id": t.pk, "name": t.name, "temperature": round(t.temperature, 3)} for t in topics],
            "articles": enrich(arts),
        })
