from celery import shared_task


@shared_task(queue="maintenance")
def recompute_temperature() -> int:
    from topics.service import recompute_all

    return recompute_all()
