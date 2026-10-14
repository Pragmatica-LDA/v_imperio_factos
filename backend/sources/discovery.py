"""Descoberta: lê um ponto de entrada e regista os itens novos (ou actualiza os conhecidos)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from core import parameters
from crawl import failures, http, ratelimit, storage
from crawl.ingest import item_reference_date, register_item
from parsers import registry
from sources.models import DiscoveryRun, EntryPoint

log = logging.getLogger(__name__)


def expand_urls(ep: EntryPoint, now=None) -> list[str]:
    """URLs a ler. sitemap_daily: template {yyyy}{mm}{dd} para hoje e os `days_back` dias anteriores."""
    if ep.kind != "sitemap_daily":
        return [ep.url]
    now = timezone.localtime(now or timezone.now())
    days = int((ep.config or {}).get("days_back", 1))
    out = []
    for i in range(days + 1):
        d = now - timedelta(days=i)
        out.append(ep.url.format(yyyy=f"{d.year:04d}", mm=f"{d.month:02d}", dd=f"{d.day:02d}"))
    return out


def _get(ep: EntryPoint, url: str, run: DiscoveryRun) -> http.HttpResult | None:
    ratelimit.acquire_blocking(ep.site)
    res = http.get(url)
    run.urls_fetched.append({"url": url, "status": res.status, "ms": res.duration_ms})
    kind = http.failure_kind(res)
    if kind or res.status != 200:
        failures.record(url=url, kind=kind or "http_other", http_status=res.status,
                        error=res.error or f"HTTP {res.status}", entrypoint=ep)
        run.error += f"{url}: {res.error or res.status}\n"
        return None
    return res


def run_entrypoint(ep: EntryPoint) -> DiscoveryRun:
    site = ep.site
    run = DiscoveryRun.objects.create(entrypoint=ep)
    max_age = timedelta(hours=float(parameters.get("discovery.max_item_age_h")))
    now = timezone.now()
    try:
        targets: list[tuple[str, str]] = []   # (kind dos itens, url)
        if ep.kind == "sitemap_index":
            res = _get(ep, ep.url, run)
            if res is not None:
                run.http_status = res.status
                for child in registry.sitemap_index(site.parser_module, res.text, ep.config):
                    targets.append(("sitemap", child))
        else:
            targets = [(ep.kind, u) for u in expand_urls(ep, now)]

        any_ok = False
        for kind, url in targets:
            res = _get(ep, url, run)
            if res is None:
                continue
            any_ok = True
            run.http_status = res.status
            if kind == "homepage":
                storage.save_raw(site.slug, "homepage", ep.name, res.text)
            items = registry.discover(site.parser_module, kind, res.text, url, include_excluded=True)
            for item in items:
                run.found += 1
                if item.excluded_reason:
                    run.excluded += 1
                    continue
                ref = item_reference_date(item)
                if ref is not None and now - ref > max_age:
                    run.skipped_old += 1
                    continue
                _, created = register_item(site, ep, item, run=run)
                if created:
                    run.new += 1
                else:
                    run.updated += 1
        run.ok = any_ok and not run.error
        if any_ok and not run.error:
            failures.resolve(entrypoint=ep)
    except Exception as exc:  # noqa: BLE001 — a execução fica registada com o erro
        log.exception("descoberta %s falhou", ep)
        run.ok = False
        run.error += f"{type(exc).__name__}: {exc}"
        failures.record(url=ep.url, kind="parse" if "parse" in type(exc).__name__.lower() else "other",
                        error=run.error, entrypoint=ep)
    run.finished_at = timezone.now()
    run.save()
    return run
