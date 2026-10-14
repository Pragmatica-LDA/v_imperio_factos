"""Ligação Redis para locks e rate limit (a instância da cache; os testes trocam por um fake)."""

from django_redis import get_redis_connection


def conn():
    return get_redis_connection("default")
