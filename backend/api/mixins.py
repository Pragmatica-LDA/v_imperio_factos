"""Base das viewsets da API: auditoria de todas as escritas e idempotência dos POST.

- Auditoria: cada escrita grava um `AuditLog` com o estado antes e depois (dados do serializer) e o actor.
- Idempotência: um POST com o header `Idempotency-Key` guarda a resposta em `IdempotencyKey`; uma repetição
  com a mesma chave (do mesmo actor) devolve a resposta guardada sem voltar a executar a acção.
"""

from __future__ import annotations

import json

from django.db import IntegrityError, transaction
from rest_framework import status, viewsets
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from core.models import AuditLog, IdempotencyKey

IDEMPOTENCY_HEADER = "HTTP_IDEMPOTENCY_KEY"


def to_json(data):
    """Dados do serializer → JSON puro (datas, decimais…), para guardar em JSONField."""
    if data is None:
        return None
    return json.loads(JSONRenderer().render(data))


def object_type(obj_or_model) -> str:
    return obj_or_model._meta.label


def audit(request, action: str, obj=None, *, before=None, after=None, extra=None,
          obj_type: str | None = None, obj_id=None) -> AuditLog:
    """Grava uma linha de auditoria. `before`/`after` são dados serializados (ou None)."""
    user = request.user if request.user and request.user.is_authenticated else None
    return AuditLog.objects.create(
        actor=user,
        action=action,
        object_type=obj_type or (object_type(obj) if obj is not None else ""),
        object_id=str(obj_id if obj_id is not None else (obj.pk if obj is not None else "")),
        before=to_json(before),
        after=to_json(after),
        extra=to_json(extra or {}),
    )


class _IdempotentReplay(Exception):
    def __init__(self, response: Response):
        self.response = response


class IdempotencyMixin:
    """POST com `Idempotency-Key`: a primeira resposta (< 500) fica guardada e é devolvida nas repetições."""

    def _idempotency_key(self, request) -> str | None:
        if request.method != "POST":
            return None
        key = (request.META.get(IDEMPOTENCY_HEADER) or "").strip()
        return key[:200] or None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)   # autenticação e permissões primeiro
        key = self._idempotency_key(request)
        if not key:
            return
        stored = IdempotencyKey.objects.filter(actor=request.user, key=key).first()
        if stored is None:
            return
        if stored.method != request.method or stored.path != request.path:
            raise _IdempotentReplay(Response(
                {"detail": "Idempotency-Key já usada noutro pedido.", "path": stored.path},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY))
        resp = Response(stored.response, status=stored.status_code)
        resp["Idempotent-Replay"] = "true"
        raise _IdempotentReplay(resp)

    def handle_exception(self, exc):
        if isinstance(exc, _IdempotentReplay):
            return exc.response
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        key = self._idempotency_key(request)
        if (key and request.user and request.user.is_authenticated and response.status_code < 500
                and not response.has_header("Idempotent-Replay")):
            try:
                with transaction.atomic():
                    IdempotencyKey.objects.create(
                        key=key, actor=request.user, method=request.method, path=request.path[:500],
                        status_code=response.status_code, response=to_json(getattr(response, "data", None)))
            except IntegrityError:
                pass   # corrida entre dois pedidos com a mesma chave: fica a primeira resposta
        return response


class BaseViewSet(IdempotencyMixin, viewsets.GenericViewSet):
    """Base de todas as viewsets (também as só de leitura, por causa das acções POST)."""


class ReadOnlyViewSet(IdempotencyMixin, viewsets.ReadOnlyModelViewSet):
    pass


class AuditedModelViewSet(IdempotencyMixin, viewsets.ModelViewSet):
    """CRUD com auditoria: create/update/destroy gravam AuditLog (antes/depois, actor=request.user)."""

    def _snapshot(self, instance):
        return self.get_serializer(instance).data

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            audit(self.request, "create", instance, after=self._snapshot(instance))

    def perform_update(self, serializer):
        with transaction.atomic():
            before = to_json(self._snapshot(serializer.instance))
            instance = serializer.save()
            audit(self.request, "update", instance, before=before, after=self._snapshot(instance))

    def perform_destroy(self, instance):
        with transaction.atomic():
            before = self._snapshot(instance)
            pk = instance.pk
            instance.delete()
            audit(self.request, "delete", obj_type=object_type(instance), obj_id=pk, before=before)
