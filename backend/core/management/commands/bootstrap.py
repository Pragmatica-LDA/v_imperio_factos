from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cria o que falta (parâmetros, fontes, tarefas periódicas). Idempotente: nunca altera o que existe."

    def handle(self, *args, **options):
        from core.parameters import ensure_defaults

        self.stdout.write(f"Parâmetros criados: {ensure_defaults()}")
        try:
            from sources.seed import ensure_sources
            from crawl.schedules import ensure_periodic_tasks
        except ImportError as exc:  # durante o desenvolvimento das apps
            self.stdout.write(f"bootstrap parcial: {exc}")
            return
        self.stdout.write(f"Fontes: {ensure_sources()}")
        self.stdout.write(f"Tarefas periódicas: {ensure_periodic_tasks()}")
        from topics.seed import ensure_taxonomy

        self.stdout.write(f"Taxonomia de temas: {ensure_taxonomy()}")
