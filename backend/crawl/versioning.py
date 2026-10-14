"""Versões: impressão digital do conteúdo extraído e diff entre versões.

Só o conteúdo editorial entra no hash (título, lead, corpo, autores, tags). Datas de actualização,
imagens e metadados de extracção ficam de fora: mudam sem a notícia mudar.
"""

from __future__ import annotations

import difflib
import hashlib
import json


def _norm(s: str | None) -> str:
    return " ".join((s or "").split())


def editorial_view(content: dict) -> dict:
    return {
        "title": _norm(content.get("title")),
        "lead": _norm(content.get("lead")),
        "body": [[b.get("kind"), _norm(b.get("text"))] for b in content.get("body") or []],
        "authors": sorted(_norm(a.get("name")) for a in content.get("authors") or []),
        "tags": sorted(_norm(t).lower() for t in content.get("tags") or []),
    }


def content_hash(content: dict) -> str:
    raw = json.dumps(editorial_view(content), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plain_text(content: dict) -> str:
    parts = [_norm(content.get("title")), _norm(content.get("lead"))]
    parts += [_norm(b.get("text")) for b in content.get("body") or []]
    return "\n\n".join(p for p in parts if p)


def diff(prev: dict | None, new: dict) -> tuple[dict, float]:
    """Diff por campo e por bloco + rácio de alteração do texto (0 = igual, 1 = tudo diferente)."""
    if prev is None:
        return {}, 0.0
    a, b = editorial_view(prev), editorial_view(new)
    out: dict = {}
    for f in ("title", "lead"):
        if a[f] != b[f]:
            out[f] = {"before": a[f], "after": b[f]}
    for f in ("authors", "tags"):
        if a[f] != b[f]:
            out[f] = {"added": sorted(set(b[f]) - set(a[f])), "removed": sorted(set(a[f]) - set(b[f]))}
    ab, bb = [t for _, t in a["body"]], [t for _, t in b["body"]]
    if ab != bb:
        ops = []
        sm = difflib.SequenceMatcher(a=ab, b=bb, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                ops.append({"op": tag, "before": ab[i1:i2], "after": bb[j1:j2], "at": [i1, j1]})
        out["body"] = ops
    ta, tb = plain_text(prev), plain_text(new)
    ratio = 1.0 - difflib.SequenceMatcher(a=ta.split(), b=tb.split(), autojunk=False).ratio()
    return out, round(ratio, 4)
