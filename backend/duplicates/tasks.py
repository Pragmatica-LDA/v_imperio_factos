from celery import shared_task


@shared_task(queue="analysis")
def detect_duplicates(version_id: int) -> dict:
    from duplicates.service import detect

    return detect(version_id)
