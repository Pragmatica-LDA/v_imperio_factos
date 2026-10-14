from django.core.management.base import BaseCommand
from django.db import transaction

from crawl import versioning
from crawl.models import Article, Version
from parsers.base import strip_html

TEXT_FIELDS = ("title", "lead", "byline_raw", "section", "subsection")


def clean_content(content: dict) -> dict:
    c = dict(content)
    for f in TEXT_FIELDS:
        if c.get(f):
            c[f] = strip_html(c[f])
    c["tags"] = [t for t in (strip_html(t) for t in c.get("tags") or []) if t]
    c["body"] = [{**b, "text": strip_html(b.get("text")) or "",
                  "links": [{**lk, "text": strip_html(lk.get("text")) or ""} for lk in b.get("links") or []]}
                 for b in c.get("body") or []]
    c["authors"] = [{**a, "name": strip_html(a.get("name")) or a.get("name")} for a in c.get("authors") or []]
    c["images"] = [{**i, "caption": strip_html(i.get("caption")), "credit_raw": strip_html(i.get("credit_raw"))}
                   for i in c.get("images") or []]
    return c


class Command(BaseCommand):
    help = ("Remove HTML dos textos já guardados (títulos e versões) e recalcula hash e texto das versões, "
            "para a próxima revisita não criar uma versão falsa. Idempotente.")

    def handle(self, *args, **options):
        articles = versions = 0
        with transaction.atomic():
            for a in Article.objects.filter(title__regex=r"<[A-Za-z/]|&[a-z#0-9]+;"):
                a.title = strip_html(a.title) or ""
                a.section = strip_html(a.section) or ""
                a.save(update_fields=["title", "section"])
                articles += 1
            for v in Version.objects.all().iterator():
                new = clean_content(v.content)
                if new != v.content:
                    v.content = new
                    v.content_hash = versioning.content_hash(new)
                    v.text = versioning.plain_text(new)
                    v.save(update_fields=["content", "content_hash", "text"])
                    versions += 1
        self.stdout.write(f"Notícias corrigidas: {articles} · versões corrigidas: {versions}")
