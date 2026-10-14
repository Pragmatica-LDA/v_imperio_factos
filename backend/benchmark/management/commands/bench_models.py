"""Lista as ModelConfigs e os modelos do servidor Ollama, e cria configs para modelos Ollama."""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError

from benchmark.llm.ollama_provider import list_models
from benchmark.models import ModelConfig


class Command(BaseCommand):
    help = "Modelos do benchmark: --list, --list-ollama, --add-ollama <modelo> …"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="ModelConfigs na BD.")
        parser.add_argument("--list-ollama", action="store_true", help="Modelos descarregados no servidor Ollama.")
        parser.add_argument("--add-ollama", nargs="+", metavar="MODELO",
                            help="Cria ModelConfigs Ollama (ex.: qwen3:14b). 'all' = todos os do servidor.")
        parser.add_argument("--url", help="URL do Ollama (por omissão OLLAMA_BASE_URL).")
        parser.add_argument("--concurrency", type=int, default=1)
        parser.add_argument("--num-ctx", type=int, help="num_ctx a gravar nos params.")
        parser.add_argument("--think", choices=["true", "false", "low", "medium", "high"],
                            help="Grava think nos params (modelos com raciocínio; gpt-oss aceita low/medium/high).")
        parser.add_argument("--repair-attempts", type=int, default=2,
                            help="Repetições com os erros quando a resposta falha o schema.")

    def handle(self, *args, **options):
        if options["list_ollama"] or options["add_ollama"] == ["all"]:
            try:
                server_models = list_models(options["url"])
            except Exception as exc:  # noqa: BLE001
                raise CommandError(f"Ollama inacessível: {exc}") from exc
        if options["list_ollama"]:
            for m in server_models:
                details = m.get("details", {})
                self.stdout.write(f"{m['name']:<40} {details.get('parameter_size', ''):>8} "
                                  f"{details.get('quantization_level', ''):>8} {m.get('size', 0) / 1e9:6.1f} GB")
        if options["add_ollama"]:
            names = [m["name"] for m in server_models] if options["add_ollama"] == ["all"] else options["add_ollama"]
            for model in names:
                slug = "ollama-" + re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
                # Sem structured outputs garantidos no Ollama Cloud: schema no prompt + reparações (igual aos outros).
                params = {"temperature": 0, "repair_attempts": options["repair_attempts"]}
                if options["num_ctx"]:
                    params["num_ctx"] = options["num_ctx"]
                if options["think"]:
                    params["think"] = {"true": True, "false": False}.get(options["think"], options["think"])
                _, created = ModelConfig.objects.update_or_create(
                    name=slug,
                    defaults={"provider": "ollama", "model_id": model, "base_url": options["url"] or "",
                              "params": params, "concurrency": options["concurrency"]},
                )
                self.stdout.write(f"{slug}: {'criado' if created else 'actualizado'}")
        if options["list"] or not (options["list_ollama"] or options["add_ollama"]):
            for c in ModelConfig.objects.all():
                flag = "" if c.active else " (inactivo)"
                self.stdout.write(f"{c.name:<28} {c.provider:<10} {c.model_id:<28} {c.params}{flag}")
