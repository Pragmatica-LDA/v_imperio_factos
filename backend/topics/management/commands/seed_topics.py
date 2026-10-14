from django.core.management.base import BaseCommand

from topics.seed import ensure_taxonomy


class Command(BaseCommand):
    help = "Cria a taxonomia semente dos temas (themes_seed.json do benchmark) como temas activos. Idempotente."

    def handle(self, *args, **options):
        self.stdout.write(f"{ensure_taxonomy()} temas criados")
