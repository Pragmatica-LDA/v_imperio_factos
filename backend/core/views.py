import redis
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


def _check(fn):
    try:
        fn()
        return "ok"
    except Exception as exc:  # noqa: BLE001 — o health reporta qualquer falha
        return f"erro: {exc}"


def _db():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _broker():
    redis.Redis.from_url(settings.CELERY_BROKER_URL).ping()


def _cache():
    cache.set("health", "ok", 5)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    checks = {"db": _check(_db), "broker": _check(_broker), "cache": _check(_cache)}
    ok = all(v == "ok" for v in checks.values())
    return Response({"status": "ok" if ok else "degraded", "checks": checks}, status=200 if ok else 503)
