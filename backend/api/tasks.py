from celery import shared_task


@shared_task(queue="maintenance")
def warm_front_overview():
    """Pré-calcula o /api/front/overview/ para o pedido nunca pagar o cálculo a frio."""
    from api.front import warm_overview

    warm_overview()
