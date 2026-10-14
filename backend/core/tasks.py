from celery import shared_task


@shared_task(queue="maintenance")
def ping():
    """Tarefa de diagnóstico: confirma que o worker da fila `maintenance` responde."""
    return "pong"
