"""Dashboard de fiabilidade do crawl (staff). A página consome /api/stats/crawl-health/ por fetch (sessão)."""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from sources.models import Site


@staff_member_required
@ensure_csrf_cookie
def crawl(request):
    sites = Site.objects.order_by("slug").values("slug", "name", "active")
    return render(request, "dashboard/crawl.html", {"sites": list(sites)})


@staff_member_required
def article(request, pk: int):
    """Tudo o que o Factos sabe de uma notícia: metadados, versões, análise (entidades, sentimento, fontes,
    temas, indicador de IA), duplicados e leituras."""
    from django.shortcuts import get_object_or_404

    from crawl.models import Article

    a = get_object_or_404(Article.objects.select_related("site", "revisit_topic", "first_seen_via"), pk=pk)
    versions = list(a.versions.order_by("-number"))
    wanted = request.GET.get("v")
    version = next((v for v in versions if str(v.number) == wanted), versions[0] if versions else None)
    analyses = list(version.analyses.order_by("-created_at")) if version else []
    analysis = next((x for x in analyses if x.status == "done"), None)

    entities = sources = topics = []
    sentiment = {"positivo": 0, "negativo": 0, "neutro": 0}
    if analysis:
        entities = list(analysis.entities.select_related("entity").order_by("is_location", "entity__type",
                                                                            "entity__canonical_name"))
        for e in entities:
            if e.sentiment in sentiment and not e.is_location:
                sentiment[e.sentiment] += 1
        sources = list(analysis.sources.select_related("entity"))
        topics = list(analysis.topics.select_related("topic", "topic__parent", "edition").order_by("-weight"))

    cluster = members = None
    membership = getattr(a, "cluster_membership", None) if hasattr(a, "cluster_membership") else None
    if membership:
        cluster = membership.cluster
        members = list(cluster.members.select_related("article__site").order_by("-is_original", "-similarity"))

    content = version.content if version else {}
    return render(request, "dashboard/article.html", {
        "a": a,
        "versions": versions,
        "version": version,
        "content": content,
        "analyses": analyses,
        "analysis": analysis,
        "entities": [e for e in entities if not e.is_location],
        "locations": [e for e in entities if e.is_location],
        "sentiment": sentiment,
        "sources": sources,
        "topics": topics,
        "cluster": cluster,
        "members": members,
        "fetches": list(a.fetches.order_by("-requested_at")[:20]),
        "links": list(version.links.select_related("target_site", "target_article").order_by("position")) if version else [],
        "incoming": list(a.incoming_links.select_related("article__site").order_by("-id")[:30]),
        "urls": list(a.urls.order_by("first_seen_at")),
        "appearances": a.homepage_appearances.count(),
        "last_appearance": a.homepage_appearances.order_by("-seen_at").first(),
    })


@staff_member_required
def analyze_now(request, pk: int):
    """POST: corre já a análise LLM da versão pedida (fora da fila), mesmo que já exista uma."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect
    from django.urls import reverse
    from django.views.decorators.http import require_POST  # noqa: F401 (documentação)

    from analysis.service import analyze
    from core.models import AuditLog
    from crawl.models import Article

    a = get_object_or_404(Article, pk=pk)
    if request.method != "POST":
        return redirect("dashboard:article", pk=pk)
    number = request.POST.get("v")
    version = a.versions.filter(number=number).first() if number else a.versions.order_by("-number").first()
    if version is None:
        messages.error(request, "Esta notícia não tem versões para analisar.")
        return redirect("dashboard:article", pk=pk)
    result = analyze(version.pk, force=True)
    AuditLog.objects.create(actor=request.user, action="analyze_now", object_type="crawl.Version",
                            object_id=str(version.pk), after=result, extra={"via": "dashboard"})
    if result.get("status") == "done":
        messages.success(request, f"Análise feita: {result.get('entities', 0)} entidades, {result.get('topics', 0)} temas.")
    else:
        messages.error(request, f"Análise não ficou feita: {result.get('status')} — {result.get('error') or result.get('reason') or ''}")
    return redirect(f"{reverse('dashboard:article', args=[pk])}?v={version.number}")


@staff_member_required
def analysis_queue(request):
    """Fila das análises LLM: pendentes, a correr, feitas, falhadas, orçamento e ritmo."""
    from datetime import timedelta

    import redis
    from django.conf import settings
    from django.db.models import Avg, Count, Exists, OuterRef, Q
    from django.db.models.functions import TruncHour
    from django.utils import timezone

    from analysis.llm import load_config
    from analysis.models import Analysis
    from analysis.service import budget_left, used_today
    from core import parameters
    from crawl.models import Version

    now = timezone.now()
    stale_min = float(parameters.get("analysis.stale_running_min"))
    try:
        broker = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        queue_len = {q: broker.llen(q) for q in ("analysis", "enrichment")}
    except Exception:  # noqa: BLE001 — a página mostra o resto mesmo sem broker
        queue_len = {"analysis": None, "enrichment": None}

    by_status = dict(Analysis.objects.values_list("status").annotate(n=Count("id")))
    has_analysis = Analysis.objects.filter(version=OuterRef("pk"))
    without = (Version.objects.filter(article__status="active").annotate(has=Exists(has_analysis))
               .filter(has=False))
    hour_ago = now - timedelta(hours=1)
    last_hour = Analysis.objects.filter(status="done", finished_at__gte=hour_ago)
    done_last_hour = last_hour.count()
    latencies = [u.get("latency_ms") for u in last_hour.values_list("usage", flat=True) if u and u.get("latency_ms")]
    pending_total = without.count() + by_status.get("pending", 0) + by_status.get("skipped_budget", 0)
    eta_min = round(pending_total / done_last_hour * 60) if done_last_hour else None

    per_hour = list(
        Analysis.objects.filter(finished_at__gte=now - timedelta(hours=24))
        .annotate(h=TruncHour("finished_at")).values("h")
        .annotate(done=Count("id", filter=Q(status="done")), failed=Count("id", filter=Q(status="failed")))
        .order_by("h")
    )
    by_model = list(Analysis.objects.filter(status="done").values("provider", "model")
                    .annotate(n=Count("id")).order_by("-n"))

    rel = ("version__article__site",)
    cfg = load_config()
    running = list(Analysis.objects.filter(status="running").select_related(*rel).order_by("started_at")[:30])
    for x in running:
        x.is_stale = bool(x.started_at and now - x.started_at > timedelta(minutes=stale_min))
    return render(request, "dashboard/analysis.html", {
        "now": now,
        "cfg": cfg,
        "queue_len": queue_len,
        "by_status": by_status,
        "without_count": without.count(),
        "pending_total": pending_total,
        "done_last_hour": done_last_hour,
        "avg_latency_s": round(sum(latencies) / len(latencies) / 1000, 1) if latencies else None,
        "eta_min": eta_min,
        "used_today": used_today(now),
        "daily_limit": parameters.get("analysis.daily_limit"),
        "budget_left": budget_left(now),
        "enabled": parameters.get("analysis.enabled"),
        "stale_min": stale_min,
        "per_hour": [{"h": r["h"].isoformat(), "done": r["done"], "failed": r["failed"]} for r in per_hour],
        "by_model": by_model,
        "running": running,
        "waiting": list(without.select_related("article__site").order_by("created_at")[:20]),
        "deferred": list(Analysis.objects.filter(status__in=["pending", "skipped_budget"]).select_related(*rel)
                         .order_by("created_at")[:20]),
        "failed": list(Analysis.objects.filter(status="failed").select_related(*rel).order_by("-finished_at")[:20]),
        "done": list(Analysis.objects.filter(status="done").select_related(*rel)
                     .annotate(n_entities=Count("entities", distinct=True), n_topics=Count("topics", distinct=True))
                     .order_by("-finished_at")[:20]),
    })
