"""Importa para a amostra do benchmark os artigos extraídos pelos parsers da PoC (sites/out/*.json)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from benchmark.models import SampleArticle

BLOCK_PREFIX = {"h2": "## ", "h3": "### ", "li": "- ", "quote": "> "}


def body_text(blocks: list[dict]) -> str:
    return "\n\n".join(f"{BLOCK_PREFIX.get(b.get('kind'), '')}{b['text'].strip()}" for b in blocks if b.get("text"))


def parse_dt(value: str | None):
    if not value or len(value) <= 10:
        return None
    return datetime.fromisoformat(value)


class Command(BaseCommand):
    help = "Importa artigos (JSON dos parsers) para a amostra do benchmark. Idempotente: o ficheiro mais recente ganha."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="*", help="Ficheiros ou pastas (por omissão ARTICLES_IMPORT_DIR).")

    def handle(self, *args, **options):
        paths = [Path(p) for p in options["paths"]] or [Path(settings.ARTICLES_IMPORT_DIR)]
        files = []
        for path in paths:
            if path.is_dir():
                files += sorted(path.glob("*_article*.json"))
            elif path.exists():
                files.append(path)
            else:
                raise CommandError(f"Não existe: {path}")

        imported, skipped = 0, []
        for f in sorted(files, key=lambda p: p.name):
            data = json.loads(f.read_text(encoding="utf-8"))
            site = f.name.split("_article")[0]
            aid = data.get("site_article_id")
            reason = None
            if not aid:
                reason = "sem site_article_id"
            elif data.get("out_of_scope"):
                reason = f"fora de âmbito ({data['out_of_scope']})"
            elif data.get("body_complete") is False:
                reason = "corpo incompleto"
            elif not data.get("body"):
                reason = "corpo vazio"
            if reason:
                skipped.append(f"{f.name}: {reason}")
                continue
            authors = ", ".join(a["name"] for a in data.get("authors", []))
            SampleArticle.objects.update_or_create(
                site=site, site_article_id=aid,
                defaults={
                    "url": data.get("canonical_url") or data.get("url") or "",
                    "title": data.get("title") or "",
                    "lead": data.get("lead") or "",
                    "body": body_text(data["body"]),
                    "byline": data.get("byline_raw") or authors,
                    "section": " / ".join(x for x in (data.get("section"), data.get("subsection")) if x),
                    "tags": data.get("tags") or [],
                    "piece_type_site": data.get("piece_type") or "",
                    "published_at": parse_dt(data.get("published_at")),
                    "word_count": data.get("word_count") or 0,
                    "raw": data,
                    "source_file": f.name,
                },
            )
            imported += 1

        self.stdout.write(f"{imported} ficheiros importados · {SampleArticle.objects.count()} artigos na amostra")
        for s in skipped:
            self.stdout.write(f"  ignorado: {s}")
