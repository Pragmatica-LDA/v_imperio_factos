from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolate(settings, tmp_path):
    """Cache em memória (sem Redis), HTML em tmp, Celery síncrono e sem chamadas reais."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.RAW_HTML_ROOT = tmp_path / "raw"
    settings.CELERY_TASK_ALWAYS_EAGER = False
    from django.core.cache import cache

    cache.clear()


class FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, px=None, ex=None):
        if px is not None:   # rate limit: nos testes nunca espera
            return True
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def pttl(self, key):
        return 100 if key in self.data else -2

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("core.redis.conn", lambda: fake)
    return fake


@pytest.fixture
def seeded(db):
    from core.parameters import ensure_defaults
    from sources.seed import ensure_sources

    ensure_defaults()
    ensure_sources()
