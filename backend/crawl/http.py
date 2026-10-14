"""Cliente HTTP do crawl. Segue redirects à mão para guardar a cadeia (301 vs 302 importa nas versões)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from core import parameters

MAX_REDIRECTS = 5


@dataclass
class HttpResult:
    url: str
    status: int | None = None
    final_url: str = ""
    text: str = ""
    chain: list[dict] = field(default_factory=list)   # [{"status": 301, "url": "...", "location": "..."}]
    duration_ms: int = 0
    error_kind: str | None = None   # timeout | network | too_large
    error: str = ""

    @property
    def permanent_redirect(self) -> bool:
        return any(h["status"] in (301, 308) for h in self.chain)


def _headers() -> dict:
    return {
        "User-Agent": parameters.get("crawl.user_agent"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9",
    }


def get(url: str, client: httpx.Client | None = None) -> HttpResult:
    timeout = float(parameters.get("crawl.timeout_s"))
    max_bytes = int(parameters.get("crawl.max_bytes"))
    own = client is None
    client = client or httpx.Client(headers=_headers(), timeout=timeout, follow_redirects=False)
    res = HttpResult(url=url)
    started = time.monotonic()
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            resp = client.get(current)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                nxt = urljoin(current, resp.headers["location"])
                res.chain.append({"status": resp.status_code, "url": current, "location": nxt})
                current = nxt
                continue
            res.status = resp.status_code
            res.final_url = str(resp.url)
            if len(resp.content) > max_bytes:
                res.error_kind, res.error = "too_large", f"{len(resp.content)} bytes"
            else:
                res.text = resp.text
            break
        else:
            res.error_kind, res.error = "network", "demasiados redirects"
    except httpx.TimeoutException as exc:
        res.error_kind, res.error = "timeout", str(exc) or "timeout"
    except httpx.HTTPError as exc:
        res.error_kind, res.error = "network", f"{type(exc).__name__}: {exc}"
    finally:
        res.duration_ms = int((time.monotonic() - started) * 1000)
        if own:
            client.close()
    return res


def failure_kind(res: HttpResult) -> str | None:
    """Tipo de falha técnica, ou None se a resposta tem significado editorial (200, 404, 410)."""
    if res.error_kind:
        return "timeout" if res.error_kind == "timeout" else "network"
    if res.status is None:
        return "network"
    if res.status >= 500:
        return "http_5xx"
    if res.status == 403:
        return "http_403"
    if res.status == 429:
        return "http_429"
    if res.status in (200, 404, 410):
        return None
    return "http_other"
