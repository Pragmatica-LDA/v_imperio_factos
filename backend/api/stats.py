"""Estatísticas gerais e fiabilidade do crawl (/api/stats/, /api/stats/crawl-health/).

O crawl-health agrega na BD (TruncHour/TruncDay + Count), por site e período, e calcula o estado de cada site
(ok | warn | alert) com os limiares `quality.*`. Serve o dashboard Django e, mais tarde, o frontend React.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import connection
from django.db.models import Avg, Count, Q
from django.db.models.functions import Coalesce, TruncDate, TruncDay, TruncHour
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from analysis.models import Analysis
from core import parameters
from crawl.models import Article, Fetch, TechnicalFailure, Version
from sources.models import DiscoveryRun, Site

# Leitura bem-sucedida = HTTP e parse correram bem (o resultado editorial pode ser "fora de âmbito" ou "apagada").
OK_OUTCOMES = ("ok", "unchanged", "out_of_scope", "deleted", "redirect")
# Não é uma tentativa: a leitura foi adiada pelo rate limit.
NOT_ATTEMPTS = ("rate_limited",)
LEVELS = {"ok": 0, "warn": 1, "alert": 2}
_RELATIVE = re.compile(r"^(\d+)\s*([hd])$")


def _ratio(a, b):
    return round(a / b, 4) if b else None


# /api/stats/ ----------------------------------------------------------------------------------------------------

class StatsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        """Contagens gerais: notícias por site × estado, séries diárias, análises e falhas abertas."""
        data = cache.get("api:stats")
        if data is None:
            data = compute_stats()
            cache.set("api:stats", data, int(parameters.get("cache.stats_s")))
        return Response(data)


def compute_stats() -> dict:
    days = int(parameters.get("stats.daily_days"))
    since = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    by_site: dict[str, dict[str, int]] = {}
    for r in Article.objects.values("site__slug", "status").annotate(n=Count("id")).order_by():
        by_site.setdefault(r["site__slug"], {})[r["status"]] = r["n"]

    def daily(qs, field):
        rows = (qs.filter(**{f"{field}__gte": since}).annotate(d=TruncDate(field)).values("d")
                .annotate(n=Count("id")).order_by("d"))
        got = {r["d"].isoformat(): r["n"] for r in rows}
        return [{"date": (since + timedelta(days=i)).date().isoformat(),
                 "n": got.get((since + timedelta(days=i)).date().isoformat(), 0)} for i in range(days)]

    failures = (TechnicalFailure.objects.filter(status__in=("open", "retrying")).values("kind")
                .annotate(n=Count("id")).order_by())
    return {
        "generated_at": timezone.now().isoformat(),
        "articles_by_site_status": by_site,
        "articles_total": sum(sum(v.values()) for v in by_site.values()),
        "daily": {
            "new_articles": daily(Article.objects, "first_seen_at"),
            "versions": daily(Version.objects, "created_at"),
            "fetches": daily(Fetch.objects, "requested_at"),
        },
        "analyses_by_status": {r["status"]: r["n"] for r in
                               Analysis.objects.values("status").annotate(n=Count("id")).order_by()},
        "open_failures": {r["kind"]: r["n"] for r in failures},
        "open_failures_total": sum(r["n"] for r in failures),
    }


# /api/stats/crawl-health/ ---------------------------------------------------------------------------------------

def parse_since(raw: str | None, bucket: str) -> datetime:
    now = timezone.now()
    if not raw:
        if bucket == "hour":
            return now - timedelta(hours=float(parameters.get("stats.hour_window_h")))
        return now - timedelta(days=float(parameters.get("stats.day_window_d")))
    m = _RELATIVE.match(raw.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - (timedelta(hours=n) if unit == "h" else timedelta(days=n))
    dt = parse_datetime(raw)
    if dt is None:
        d = parse_date(raw)
        if d is None:
            raise ValidationError({"since": "Formato inválido: ISO 8601 (data ou data-hora) ou relativo (48h, 30d)."})
        dt = datetime(d.year, d.month, d.day)
    return dt if timezone.is_aware(dt) else timezone.make_aware(dt)


def _thresholds() -> dict:
    return {
        "success_warn": float(parameters.get("quality.success_warn")),
        "success_alert": float(parameters.get("quality.success_alert")),
        "drop_alert": float(parameters.get("quality.drop_alert")),
        "moving_avg_buckets": int(parameters.get("quality.moving_avg_buckets")),
        "min_bucket_fetches": int(parameters.get("quality.min_bucket_fetches")),
    }


def _quality_codes(since: datetime, site_id: int | None) -> list[tuple]:
    """(site_id, kind, code, n) dos erros/avisos em Fetch.quality — agregado no Postgres."""
    fetch_t, article_t = Fetch._meta.db_table, Article._meta.db_table
    arr = ("CASE WHEN jsonb_typeof(f.quality->'{k}') = 'array' THEN f.quality->'{k}' ELSE '[]'::jsonb END")
    sql = f"""
        SELECT a.site_id, q.kind, q.code, COUNT(*) AS n
        FROM {fetch_t} f
        JOIN {article_t} a ON a.id = f.article_id
        CROSS JOIN LATERAL (
            SELECT 'error' AS kind, jsonb_array_elements_text({arr.format(k="errors")}) AS code
            UNION ALL
            SELECT 'warning' AS kind, jsonb_array_elements_text({arr.format(k="warnings")}) AS code
        ) q
        WHERE f.requested_at >= %s {"AND a.site_id = %s" if site_id else ""}
        GROUP BY a.site_id, q.kind, q.code
        ORDER BY n DESC
    """
    with connection.cursor() as cur:
        cur.execute(sql, [since, site_id] if site_id else [since])
        return cur.fetchall()


def _check_rate(reasons, code, label, value, avg, th):
    if value is None:
        return
    if value < th["success_alert"]:
        reasons.append({"level": "alert", "code": code, "value": value, "threshold": th["success_alert"],
                        "message": f"{label} {value:.0%} abaixo do limiar de alerta ({th['success_alert']:.0%})"})
    elif value < th["success_warn"]:
        reasons.append({"level": "warn", "code": code, "value": value, "threshold": th["success_warn"],
                        "message": f"{label} {value:.0%} abaixo do limiar de aviso ({th['success_warn']:.0%})"})
    if avg is not None and avg - value >= th["drop_alert"]:
        reasons.append({"level": "alert", "code": f"{code}_drop", "value": value, "moving_avg": avg,
                        "threshold": th["drop_alert"],
                        "message": f"{label} caiu de {avg:.0%} (média móvel) para {value:.0%}"})


def _site_status(series: list[dict], ep_runs: dict, th: dict, site_active: bool) -> tuple[str, list, dict]:
    reasons: list[dict] = []
    k = th["moving_avg_buckets"]
    eligible = [b for b in series if b["fetch_total"] >= th["min_bucket_fetches"]]
    latest: dict = {}
    if eligible:
        cur, prev = eligible[-1], eligible[-1 - k:-1]

        def avg(field):
            vals = [b[field] for b in prev if b[field] is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        latest = {"bucket": cur["bucket"], "fetch_total": cur["fetch_total"], "success_rate": cur["success_rate"],
                  "quality_ok_rate": cur["quality_ok_rate"], "success_rate_avg": avg("success_rate"),
                  "quality_ok_rate_avg": avg("quality_ok_rate")}
        _check_rate(reasons, "success_rate", "Taxa de sucesso", cur["success_rate"], latest["success_rate_avg"], th)
        _check_rate(reasons, "quality_ok_rate", "Taxa de qualidade", cur["quality_ok_rate"],
                    latest["quality_ok_rate_avg"], th)
    elif site_active:
        reasons.append({"level": "warn", "code": "no_data",
                        "message": f"Sem períodos com pelo menos {th['min_bucket_fetches']} leituras"})

    # Descoberta: por ponto de entrada (cada um tem a sua escala de itens encontrados).
    for ep_name, buckets in ep_runs.items():
        cur, prev = buckets[-1], buckets[-1 - k:-1]
        ok_rate = _ratio(cur["ok"], cur["runs"])
        if ok_rate is not None and ok_rate < th["success_alert"]:
            reasons.append({"level": "alert", "code": "discovery_failed", "entrypoint": ep_name, "value": ok_rate,
                            "message": f"Descoberta {ep_name}: só {ok_rate:.0%} das execuções correram bem"})
        prev_found = [b["found_avg"] for b in prev if b["found_avg"] is not None]
        if cur["found_avg"] is not None and prev_found:
            avg_found = sum(prev_found) / len(prev_found)
            drop = (avg_found - cur["found_avg"]) / avg_found if avg_found else 0
            if drop >= th["drop_alert"]:
                reasons.append({
                    "level": "alert", "code": "discovery_drop", "entrypoint": ep_name, "value": cur["found_avg"],
                    "moving_avg": round(avg_found, 2), "threshold": th["drop_alert"],
                    "message": (f"Descoberta {ep_name}: itens por execução caíram de {avg_found:.0f} "
                                f"para {cur['found_avg']:.0f} (parser partido?)")})
    level = max((LEVELS[r["level"]] for r in reasons), default=0)
    return next(name for name, v in LEVELS.items() if v == level), reasons, latest


def compute_crawl_health(site_slug: str | None, bucket: str, since: datetime) -> dict:
    th = _thresholds()
    trunc = TruncHour if bucket == "hour" else TruncDay
    sites = Site.objects.all()
    if site_slug:
        sites = sites.filter(slug=site_slug)
        if not sites.exists():
            raise ValidationError({"site": "Site desconhecido."})
    sites = list(sites)
    site_id = sites[0].pk if site_slug else None

    fq = Fetch.objects.filter(requested_at__gte=since).exclude(outcome__in=NOT_ATTEMPTS)
    rq = DiscoveryRun.objects.filter(started_at__gte=since)
    if site_id:
        fq, rq = fq.filter(article__site_id=site_id), rq.filter(entrypoint__site_id=site_id)

    fetch_rows = (fq.annotate(b=trunc("requested_at")).values("article__site_id", "b")
                  .annotate(total=Count("id"),
                            ok=Count("id", filter=Q(outcome__in=OK_OUTCOMES)),
                            tech=Count("id", filter=Q(outcome="technical_failure")),
                            parse=Count("id", filter=Q(outcome="parse_error")),
                            q_n=Count("id", filter=Q(quality_ok__isnull=False)),
                            q_ok=Count("id", filter=Q(quality_ok=True)))
                  .order_by("b"))
    site_runs = (rq.annotate(b=trunc("started_at")).values("entrypoint__site_id", "b")
                 .annotate(runs=Count("id"), n_ok=Count("id", filter=Q(ok=True)),
                           found_avg=Avg("found", filter=Q(ok=True)))
                 .order_by("b"))
    ep_rows = (rq.annotate(b=trunc("started_at")).values("entrypoint__site_id", "entrypoint__name", "b")
               .annotate(runs=Count("id"), n_ok=Count("id", filter=Q(ok=True)),
                         found_avg=Avg("found", filter=Q(ok=True)))
               .order_by("b"))
    fail_rows = (TechnicalFailure.objects.filter(last_at__gte=since)
                 .annotate(site_id=Coalesce("article__site_id", "entrypoint__site_id"))
                 .values("site_id", "kind").annotate(n=Count("id")).order_by())
    if site_id:
        fail_rows = fail_rows.filter(site_id=site_id)

    series: dict[int, dict[str, dict]] = {s.pk: {} for s in sites}

    def slot(sid, b):
        key = b.isoformat()
        return series.setdefault(sid, {}).setdefault(key, {
            "bucket": key, "fetch_total": 0, "fetch_ok": 0, "technical_failures": 0, "parse_errors": 0,
            "quality_checked": 0, "quality_ok": 0, "success_rate": None, "quality_ok_rate": None,
            "discovery_runs": 0, "discovery_ok": 0, "discovery_found_avg": None})

    for r in fetch_rows:
        b = slot(r["article__site_id"], r["b"])
        b.update(fetch_total=r["total"], fetch_ok=r["ok"], technical_failures=r["tech"], parse_errors=r["parse"],
                 quality_checked=r["q_n"], quality_ok=r["q_ok"], success_rate=_ratio(r["ok"], r["total"]),
                 quality_ok_rate=_ratio(r["q_ok"], r["q_n"]))
    for r in site_runs:
        b = slot(r["entrypoint__site_id"], r["b"])
        b.update(discovery_runs=r["runs"], discovery_ok=r["n_ok"],
                 discovery_found_avg=round(r["found_avg"], 2) if r["found_avg"] is not None else None)
    ep_runs: dict[int, dict[str, list]] = {}
    for r in ep_rows:
        ep_runs.setdefault(r["entrypoint__site_id"], {}).setdefault(r["entrypoint__name"], []).append(
            {"bucket": r["b"].isoformat(), "runs": r["runs"], "ok": r["n_ok"], "found_avg": r["found_avg"]})
    failures: dict[int, dict[str, int]] = {}
    for r in fail_rows:
        failures.setdefault(r["site_id"], {})[r["kind"]] = r["n"]

    top_n = int(parameters.get("quality.top_fields"))
    codes: dict[int, list] = {}
    for sid, kind, code, n in _quality_codes(since, site_id):
        codes.setdefault(sid, []).append({"code": code, "kind": kind, "count": n})

    out = []
    for site in sites:
        ser = sorted(series.get(site.pk, {}).values(), key=lambda b: b["bucket"])
        checked = sum(b["quality_checked"] for b in ser)
        top = [{**c, "rate": _ratio(c["count"], checked)} for c in codes.get(site.pk, [])[:top_n]]
        st, reasons, latest = _site_status([b for b in ser if b["fetch_total"]], ep_runs.get(site.pk, {}), th,
                                           site.active)
        out.append({
            "site": site.slug, "name": site.name, "active": site.active, "status": st, "reasons": reasons,
            "latest": latest,
            "totals": {k: sum(b[k] for b in ser) for k in
                       ("fetch_total", "fetch_ok", "technical_failures", "parse_errors", "quality_checked",
                        "quality_ok", "discovery_runs", "discovery_ok")},
            "failures_by_kind": failures.get(site.pk, {}),
            "top_quality_fields": top,
            "discovery_by_entrypoint": {name: b[-1] for name, b in ep_runs.get(site.pk, {}).items()},
            "series": ser,
        })
    worst = max((LEVELS[s["status"]] for s in out), default=0)
    return {
        "generated_at": timezone.now().isoformat(),
        "bucket": bucket,
        "since": since.isoformat(),
        "thresholds": th,
        "status": next(name for name, v in LEVELS.items() if v == worst),
        "sites": out,
    }


class CrawlHealthView(APIView):
    @extend_schema(
        responses=OpenApiTypes.OBJECT,
        parameters=[
            OpenApiParameter("site", OpenApiTypes.STR, description="Slug do site (omissão: todos)"),
            OpenApiParameter("bucket", OpenApiTypes.STR, enum=["hour", "day"], description="Período (omissão: hour)"),
            OpenApiParameter("since", OpenApiTypes.STR,
                             description="ISO 8601 ou relativo (48h, 30d). Omissão: stats.hour_window_h / "
                                         "stats.day_window_d"),
        ])
    def get(self, request):
        """Fiabilidade do crawl por site e período, com o estado ok | warn | alert e as razões."""
        site = request.query_params.get("site") or None
        bucket = request.query_params.get("bucket") or "hour"
        if bucket not in ("hour", "day"):
            raise ValidationError({"bucket": "Usa hour ou day."})
        raw_since = request.query_params.get("since") or ""
        key = f"api:crawl-health:{site}:{bucket}:{raw_since}"
        data = cache.get(key)
        if data is None:
            data = compute_crawl_health(site, bucket, parse_since(raw_since, bucket))
            cache.set(key, data, int(parameters.get("cache.crawl_health_s")))
        return Response(data)
