import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Cria o superuser definido em DJANGO_SUPERUSER_USERNAME/PASSWORD (e EMAIL, opcional), "
        "ou actualiza a password se já existir. Sem as variáveis, não faz nada."
    )

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        if not username or not password:
            self.stdout.write("DJANGO_SUPERUSER_USERNAME/PASSWORD não definidos: superuser não criado.")
            return

        user, created = get_user_model().objects.get_or_create(username=username, defaults={"email": email})
        user.is_staff = True
        user.is_superuser = True
        if email:
            user.email = email
        user.set_password(password)
        user.save()
        self.stdout.write(f"Superuser '{username}' {'criado' if created else 'actualizado'}.")
