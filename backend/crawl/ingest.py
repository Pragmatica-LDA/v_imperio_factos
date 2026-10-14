"""Núcleo do crawl: registar itens descobertos e processar a leitura de uma notícia."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone

from core import parameters
from crawl import failures, http, quality, scheduling, storage, versioning
from crawl.models import Article, ArticleURL, Fetch, HomepageAppearance, Version
from parsers import registry
from parsers.base import ACCESS_PREMIUM, HomepageItem

log = logging.getLogger(__name__)

PREMIUM_REASON = "premium_sem_texto_integral"


def parse_dt(value: str | None, precision: str | None = "datetime") -> datetime | None:
    if not value or precision == "date":
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else timezone.make_aware(dt)


def item_reference_date(item: HomepageItem) -> datetime | None:
    """Data para o filtro de idade: publicação, ou data do URL, ou lastmod."""
    if item.published_at:
        if item.published_at_precision == "date":
            try:
                d = datetime.fromisoformat(item.published_at[:10])
                return timezone.make_aware(d.replace(hour=23, minute=59))  # fim do dia: não corta o próprio dia
            except ValueError:
                pass
        else:
            dt = parse_dt(item.published_at)
            if dt:
                return dt
    return parse_dt((item.site_meta or {}).get("lastmod"))


def find_article(site, site_article_id: str | None, urls: list[str]) -> Article | None:
    if site_article_id:
        a = Article.objects.filter(site=site, site_article_id=site_article_id).first()
        if a:
            return a
    link = ArticleURL.objects.filter(url__in=[u for u in urls if u]).select_related("article").first()
    return link.article if link else None


def add_urls(article: Article, urls: list[str], kind: str) -> None:
    for u in dict.fromkeys(u for u in urls if u):
        ArticleURL.objects.get_or_create(url=u[:1000], defaults={"article": article, "kind": kind})


def register_item(site, entrypoint, item: HomepageItem, run=None) -> tuple[Article, bool]:
    """Cria ou actualiza a notícia de um item descoberto. Devolve (artigo, criado)."""
    urls = [item.url, *item.aliases]
    for attempt in range(2):
        try:
            with transaction.atomic():
                article = find_article(site, item.site_article_id, urls)
                created = article is None
                if created:
                    article = Article.objects.create(
                        site=site,
                        site_article_id=item.site_article_id,
                        canonical_url=item.url,
                        title=item.title or "",
                        section=item.section or "",
                        published_at=parse_dt(item.published_at, item.published_at_precision),
                        access=item.access or "",
                        piece_type=item.piece_type or "",
                        agencies=item.agencies,
                        discovery_meta={**(item.site_meta or {}), "published_at": item.published_at,
                                        "via": entrypoint.kind},
                        first_seen_via=entrypoint,
                    )
                    add_urls(article, [item.url], "discovered")
                    add_urls(article, item.aliases, "alias")
                    if item.access == ACCESS_PREMIUM and site.skip_premium_on_discovery:
                        article.status, article.out_of_scope_reason = "out_of_scope", PREMIUM_REASON
                        article.save(update_fields=["status", "out_of_scope_reason"])
                    else:
                        transaction.on_commit(lambda aid=article.pk: _enqueue_fetch(aid, "new"))
                else:
                    _update_from_item(article, item, urls)
                if entrypoint.kind == "homepage":
                    HomepageAppearance.objects.create(article=article, entrypoint=entrypoint, run=run,
                                                      zone=item.zone or "", zones=item.zones, rank=item.rank)
                return article, created
        except IntegrityError:
            if attempt:
                raise
            log.info("corrida a registar %s; nova tentativa", item.url)
    raise RuntimeError("inalcançável")


def _update_from_item(article: Article, item: HomepageItem, urls: list[str]) -> None:
    fields = []
    if item.site_article_id and not article.site_article_id:
        if not Article.objects.filter(site=article.site, site_article_id=item.site_article_id).exists():
            article.site_article_id = item.site_article_id
            fields.append("site_article_id")
    add_urls(article, urls, "alias")
    meta = item.site_meta or {}
    old_lastmod = (article.discovery_meta or {}).get("lastmod")
    new_lastmod = meta.get("lastmod")
    if new_lastmod and new_lastmod != old_lastmod:
        article.discovery_meta = {**(article.discovery_meta or {}), "lastmod": new_lastmod}
        fields.append("discovery_meta")
        if old_lastmod and article.status == "active" and parameters.get("revisit.on_lastmod_change"):
            article.next_revisit_at, article.revisit_reason = timezone.now(), "lastmod do sitemap mudou"
            fields += ["next_revisit_at", "revisit_reason"]
    if fields:
        article.save(update_fields=list(dict.fromkeys(fields)))


def _enqueue_fetch(article_id: int, reason: str, queue: str = "crawl") -> None:
    from crawl.tasks import fetch_article

    fetch_article.apply_async(args=[article_id, reason], queue=queue)


def _is_article_like(url: str) -> bool:
    """Um redirect para a homepage ou para uma secção significa notícia apagada."""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    return len(segments) >= 2


def process_fetch(article: Article, reason: str, res: http.HttpResult) -> Fetch:
    """Trata a resposta HTTP de uma leitura: falhas, apagamentos, redirects, parse, versão, cadência."""
    now = timezone.now()
    site = article.site
    fetch = Fetch(article=article, url=res.url, reason=reason, http_status=res.status,
                  final_url=res.final_url, redirect_chain=res.chain, duration_ms=res.duration_ms)

    kind = http.failure_kind(res)
    if kind:
        fetch.outcome, fetch.error = "technical_failure", res.error or f"HTTP {res.status}"
        fetch.save()
        failures.record(url=res.url, kind=kind, error=fetch.error, http_status=res.status,
                        article=article, fetch_reason=reason)
        if not article.versions.exists() and article.status == "discovered":
            article.status = "failed"
        article.last_fetched_at = now
        article.save(update_fields=["status", "last_fetched_at"])
        return fetch

    failures.resolve(article=article)
    article.last_fetched_at = now

    # 404/410 ou redirect para a homepage/secção: notícia apagada (dado editorial, não erro).
    deleted_reason = ""
    if res.status in (404, 410):
        deleted_reason = f"http_{res.status}"
    elif res.chain and not _is_article_like(res.final_url):
        deleted_reason = f"redirect_{res.chain[0]['status']}_para_{urlsplit(res.final_url).path or '/'}"
    if deleted_reason:
        fetch.outcome = "deleted"
        fetch.save()
        article.status, article.deleted_reason = "deleted", deleted_reason
        scheduling.reschedule(article, now)
        article.save()
        return fetch

    # Redirect permanente para outro artigo: o novo URL fica ligado à mesma notícia.
    if res.chain and res.permanent_redirect:
        add_urls(article, [res.final_url], "redirect")

    if res.text:
        fetch.raw_path = storage.save_raw(site.slug, "article", article.site_article_id or str(article.pk), res.text)
    try:
        parsed = registry.article(site.parser_module, res.text, res.final_url or res.url)
    except Exception as exc:  # noqa: BLE001 — qualquer erro do parser é uma falha técnica de parse
        fetch.outcome, fetch.error = "parse_error", f"{type(exc).__name__}: {exc}"
        fetch.quality, fetch.quality_ok = {"ok": False, "errors": ["parse:exception"], "warnings": []}, False
        fetch.save()
        failures.record(url=res.url, kind="parse", error=fetch.error, article=article, fetch_reason=reason)
        article.save(update_fields=["last_fetched_at"])
        return fetch

    content = parsed.to_dict()
    diag = quality.diagnose(content)
    fetch.quality, fetch.quality_ok = diag, diag["ok"]

    article = _merge_if_duplicate_id(article, parsed.site_article_id)
    fetch.article = article
    _apply_parsed(article, parsed)

    if parsed.out_of_scope:
        fetch.outcome = "out_of_scope"
        fetch.save()
        article.status, article.out_of_scope_reason = "out_of_scope", parsed.out_of_scope
        scheduling.reschedule(article, now)
        article.save()
        return fetch

    article.status = "active"
    if reason == "late" or (article.published_at and now >= article.published_at
                            + timedelta(days=float(parameters.get("revisit.late_days")))):
        article.late_revisit_done = True

    digest = versioning.content_hash(content)
    with transaction.atomic():
        locked = Article.objects.select_for_update().get(pk=article.pk)
        last = locked.versions.order_by("-number").first()
        fetch.save()
        if last and last.content_hash == digest:
            fetch.outcome = "unchanged"
            fetch.save(update_fields=["outcome"])
            version = None
        else:
            fetch.outcome = "ok"
            fetch.save(update_fields=["outcome"])
            d, ratio = versioning.diff(last.content if last else None, content)
            version = Version.objects.create(
                article=article, number=(last.number + 1) if last else 1, fetch=fetch, content=content,
                content_hash=digest, text=versioning.plain_text(content), word_count=diag["word_count"] or 0,
                change_ratio=ratio, diff=d,
            )
            article.version_count = version.number
            article.change_ratio_total = round(article.change_ratio_total + ratio, 4)
        scheduling.reschedule(article, now)
        article.save()
    if version is not None:
        from crawl import links

        links.record(version)
        transaction.on_commit(lambda vid=version.pk: _enqueue_version_followups(vid))
    return fetch


def _apply_parsed(article: Article, parsed) -> None:
    article.canonical_url = parsed.canonical_url or article.canonical_url
    article.title = parsed.title or article.title
    article.section = parsed.section or article.section
    article.published_at = parse_dt(parsed.published_at, parsed.published_at_precision) or article.published_at
    article.updated_at = parse_dt(parsed.updated_at)
    article.access = parsed.access or article.access
    article.piece_type = parsed.piece_type or article.piece_type
    article.agencies = parsed.agencies or article.agencies
    if parsed.site_article_id and not article.site_article_id:
        article.site_article_id = parsed.site_article_id
    add_urls(article, [parsed.canonical_url], "canonical")
    add_urls(article, parsed.aliases, "alias")


def _merge_if_duplicate_id(article: Article, site_article_id: str | None) -> Article:
    """Observador: o ID só aparece depois do fetch. Se já existe outra notícia com esse ID, junta-as."""
    if not site_article_id or article.site_article_id == site_article_id:
        return article
    other = Article.objects.filter(site=article.site, site_article_id=site_article_id).exclude(pk=article.pk).first()
    if other is None:
        return article
    with transaction.atomic():
        ArticleURL.objects.filter(article=article).update(article=other)
        Fetch.objects.filter(article=article).update(article=other)
        HomepageAppearance.objects.filter(article=article).update(article=other)
        if not article.versions.exists():
            article.delete()
    log.info("notícia %s junta à %s (mesmo ID %s)", article.pk, other.pk, site_article_id)
    return other


def _enqueue_version_followups(version_id: int) -> None:
    from analysis.tasks import analyze_version
    from duplicates.tasks import detect_duplicates

    if parameters.get("analysis.enabled"):
        analyze_version.apply_async(args=[version_id], queue="analysis")
    detect_duplicates.apply_async(args=[version_id], queue="analysis")
