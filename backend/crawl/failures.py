"""Falhas técnicas: registo, backoff e desistência (parâmetros failures.*)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core import parameters
from crawl.models import TechnicalFailure


def _backoff(attempts: int) -> timedelta:
    steps = list(parameters.get("failures.backoff_s"))
    return timedelta(seconds=steps[min(attempts - 1, len(steps) - 1)])


def record(*, url: str, kind: str, error: str = "", http_status: int | None = None,
           article=None, entrypoint=None, fetch_reason: str = "") -> TechnicalFailure:
    max_attempts = int(parameters.get("failures.max_attempts"))
    now = timezone.now()
    qs = TechnicalFailure.objects.filter(status__in=["open", "retrying"])
    qs = qs.filter(article=article) if article is not None else qs.filter(entrypoint=entrypoint, url=url)
    failure = qs.first()
    if failure is None:
        failure = TechnicalFailure(url=url, article=article, entrypoint=entrypoint, attempts=0,
                                   fetch_reason=fetch_reason)
    failure.attempts += 1
    failure.kind, failure.http_status, failure.last_error = kind, http_status, error[:5000]
    if failure.attempts >= max_attempts:
        failure.status, failure.next_retry_at = "given_up", None
    else:
        failure.status, failure.next_retry_at = "open", now + _backoff(failure.attempts)
    failure.save()
    return failure


def resolve(*, article=None, entrypoint=None) -> int:
    qs = TechnicalFailure.objects.filter(status__in=["open", "retrying"])
    qs = qs.filter(article=article) if article is not None else qs.filter(entrypoint=entrypoint)
    return qs.update(status="resolved", next_retry_at=None)
