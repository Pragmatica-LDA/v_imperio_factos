from celery import shared_task


@shared_task(queue="analysis")
def analyze_version(version_id: int) -> dict:
    """Análise LLM de uma versão (implementação em analysis/service.py)."""
    from analysis.service import analyze

    return analyze(version_id)


@shared_task(queue="analysis")
def drain_pending() -> int:
    from analysis.service import drain

    return drain()
