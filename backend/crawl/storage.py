"""HTML completo de cada leitura, em gzip, fora da BD (RAW_HTML_ROOT)."""

from __future__ import annotations

import gzip
import re
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings


def save_raw(site_slug: str, kind: str, ident: str, text: str) -> str:
    now = datetime.now(timezone.utc)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ident)[:80] or "x"
    rel = Path(site_slug) / now.strftime("%Y/%m/%d") / f"{kind}_{safe}_{now.strftime('%H%M%S%f')}.html.gz"
    path = Path(settings.RAW_HTML_ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(text)
    return str(rel)


def load_raw(rel: str) -> str:
    with gzip.open(Path(settings.RAW_HTML_ROOT) / rel, "rt", encoding="utf-8") as fh:
        return fh.read()
