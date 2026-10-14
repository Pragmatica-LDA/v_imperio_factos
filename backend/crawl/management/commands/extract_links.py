from django.core.management.base import BaseCommand

from crawl import links
from crawl.models import Version


class Command(BaseCommand):
    help = "Regista as ligações do corpo (inline e embeds) das versões já guardadas. Idempotente."

    def handle(self, *args, **options):
        total = versions = 0
        for v in Version.objects.select_related("article__site").iterator():
            total += links.record(v)
            versions += 1
        self.stdout.write(f"Versões: {versions} · ligações registadas: {total}")
