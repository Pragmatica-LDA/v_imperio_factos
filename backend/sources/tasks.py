from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import parameters
from sources.models import EntryPoint


@shared_task(queue="discovery")
def tick_discovery() -> int:
    """Põe na fila os pontos de entrada vencidos. A cadência de cada um está na BD (interval_s)."""
    now = timezone.now()
    batch = int(parameters.get("discovery.tick_batch"))
    with transaction.atomic():
        due = list(
            EntryPoint.objects.select_for_update(skip_locked=True)
            .filter(active=True, site__active=True)
            .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
            .order_by("next_run_at")[:batch]
        )
        for ep in due:
            ep.last_run_at, ep.next_run_at = now, now + timedelta(seconds=ep.interval_s)
            ep.save(update_fields=["last_run_at", "next_run_at"])
    for ep in due:
        discover_entrypoint.apply_async(args=[ep.pk], queue="discovery")
    return len(due)


@shared_task(queue="discovery")
def discover_entrypoint(entrypoint_id: int) -> dict:
    from sources.discovery import run_entrypoint

    ep = EntryPoint.objects.select_related("site").filter(pk=entrypoint_id).first()
    if ep is None:
        return {"skipped": "não existe"}
    run = run_entrypoint(ep)
    return {"run": run.pk, "ok": run.ok, "found": run.found, "new": run.new, "updated": run.updated}
