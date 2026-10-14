"""Rate limit por site: no máximo um pedido por `min_delay_s`, partilhado por todos os workers (Redis)."""

from __future__ import annotations

import time

from core import parameters
from core import redis as core_redis


def site_delay(site) -> float:
    return float(site.min_delay_s if site.min_delay_s is not None else parameters.get("crawl.default_min_delay_s"))


def try_acquire(site) -> float:
    """Tenta reservar o slot do site. Devolve 0 se conseguiu, ou os segundos a esperar."""
    delay_ms = max(1, int(site_delay(site) * 1000))
    conn = core_redis.conn()
    key = f"ratelimit:site:{site.slug}"
    if conn.set(key, 1, nx=True, px=delay_ms):
        return 0.0
    ttl = conn.pttl(key)
    return max(ttl, 50) / 1000.0


def acquire_blocking(site, max_wait_s: float = 120.0) -> None:
    """Para a descoberta (poucos pedidos): espera pelo slot em vez de reagendar a tarefa."""
    waited = 0.0
    while True:
        wait = try_acquire(site)
        if wait == 0:
            return
        if waited > max_wait_s:
            raise TimeoutError(f"rate limit de {site.slug}: sem slot ao fim de {waited:.0f}s")
        time.sleep(wait)
        waited += wait
