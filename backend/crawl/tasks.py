import logging
import random

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from core import parameters
from core import redis as core_redis
from crawl import http, ratelimit
from crawl.ingest import process_fetch
from crawl.models import Article, TechnicalFailure

log = logging.getLogger(__name__)

FETCH_LOCK_S = 300


@shared_task(bind=True, queue="crawl", max_retries=None, acks_late=True)
def fetch_article(self, article_id: int, reason: str = "new") -> dict:
    article = Article.objects.select_related("site").filter(pk=article_id).first()
    if article is None:
        return {"skipped": "não existe"}
    if not article.site.active:
        return {"skipped": "site inactivo"}
    if article.status == "out_of_scope" and reason not in ("manual",):
        return {"skipped": "fora de âmbito"}

    wait = ratelimit.try_acquire(article.site)
    if wait:
        raise self.retry(countdown=wait + random.uniform(0, ratelimit.site_delay(article.site) * 3))

    conn = core_redis.conn()
    lock = f"fetchlock:article:{article_id}"
    if not conn.set(lock, 1, nx=True, ex=FETCH_LOCK_S):
        return {"skipped": "leitura já em curso"}
    try:
        res = http.get(article.canonical_url)
        fetch = process_fetch(article, reason, res)
    finally:
        conn.delete(lock)
    return {"fetch": fetch.pk, "outcome": fetch.outcome, "status": fetch.http_status}


@shared_task(queue="revisits")
def sweep_revisits() -> int:
    """Põe na fila revisits as notícias com next_revisit_at vencido."""
    now = timezone.now()
    batch = int(parameters.get("revisit.sweep_batch"))
    late_days = float(parameters.get("revisit.late_days"))
    with transaction.atomic():
        due = list(
            Article.objects.select_for_update(skip_locked=True)
            .filter(status="active", next_revisit_at__lte=now)
            .order_by("next_revisit_at")
            .values_list("pk", "published_at", "late_revisit_done")[:batch]
        )
        ids = [d[0] for d in due]
        Article.objects.filter(pk__in=ids).update(next_revisit_at=None, revisit_reason="em fila")
    for pk, published_at, late_done in due:
        is_late = (not late_done and published_at is not None
                   and (now - published_at).total_seconds() >= late_days * 86400)
        fetch_article.apply_async(args=[pk, "late" if is_late else "revisit"], queue="revisits")
    return len(due)


@shared_task(queue="maintenance")
def sweep_failures() -> int:
    """Novas tentativas das falhas técnicas vencidas (backoff em failures.backoff_s)."""
    from sources.tasks import discover_entrypoint

    now = timezone.now()
    with transaction.atomic():
        due = list(TechnicalFailure.objects.select_for_update(skip_locked=True)
                   .filter(status="open", next_retry_at__lte=now)[:200])
        for f in due:
            f.status = "retrying"
            f.save(update_fields=["status", "last_at"])
    for f in due:
        if f.article_id:
            fetch_article.apply_async(args=[f.article_id, "retry"], queue="crawl")
        elif f.entrypoint_id:
            discover_entrypoint.apply_async(args=[f.entrypoint_id], queue="discovery")
    return len(due)
