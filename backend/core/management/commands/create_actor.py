from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.authtoken.models import Token

from core.models import Actor


class Command(BaseCommand):
    help = (
        "Cria um actor da API (utilizador + Actor + token) e imprime o token. "
        "É o único sítio onde o token é mostrado: guarda-o (ex.: FACTOS_TOKEN)."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--kind", choices=["agent", "human"], default="agent")
        parser.add_argument("--staff", action="store_true", help="Acesso ao admin e ao dashboard")
        parser.add_argument("--description", default="")
        parser.add_argument("--rotate", action="store_true", help="Se o actor já existe, gera um token novo")

    def handle(self, *args, username, kind, staff, description, rotate, **options):
        User = get_user_model()
        with transaction.atomic():
            user, created = User.objects.get_or_create(username=username)
            if not created and not rotate:
                raise CommandError(f"'{username}' já existe. Usa --rotate para gerar um token novo.")
            if created:
                user.set_unusable_password()
            user.is_staff = staff or user.is_staff
            user.save()
            Actor.objects.update_or_create(user=user, defaults={"kind": kind, "description": description})
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
        self.stderr.write(f"Actor '{username}' ({kind}{', staff' if user.is_staff else ''}) "
                          f"{'criado' if created else 'com token novo'}.")
        self.stdout.write(token.key)
