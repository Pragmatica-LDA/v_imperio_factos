"""Tarefas periódicas do beat (django-celery-beat, na BD). Idempotente: não altera intervalos já editados."""

from django_celery_beat.models import IntervalSchedule, PeriodicTask

PERIODIC = [
    # (nome, tarefa, fila, segundos)
    ("Descoberta: tick", "sources.tasks.tick_discovery", "discovery", 60),
    ("Revisitas: sweeper", "crawl.tasks.sweep_revisits", "revisits", 300),
    ("Falhas técnicas: novas tentativas", "crawl.tasks.sweep_failures", "maintenance", 300),
    ("Temas: temperatura", "topics.tasks.recompute_temperature", "maintenance", 900),
    ("Análise: retomar pendentes", "analysis.tasks.drain_pending", "analysis", 300),
    ("Front-office: pré-calcular o overview", "api.tasks.warm_front_overview", "maintenance", 60),
]


def ensure_periodic_tasks() -> int:
    created = 0
    for name, task, queue, seconds in PERIODIC:
        interval, _ = IntervalSchedule.objects.get_or_create(every=seconds, period=IntervalSchedule.SECONDS)
        _, c = PeriodicTask.objects.get_or_create(
            name=name, defaults={"task": task, "interval": interval, "queue": queue, "enabled": True})
        created += c
    return created
