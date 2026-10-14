"""Exporta os pedidos exactos (system, schema e um user por artigo), para produzir uma baseline à mão."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from benchmark.bench import prompt as prompt_mod
from benchmark.models import PromptVersion, SampleArticle


class Command(BaseCommand):
    help = "Escreve <out>/system.txt, <out>/schema.json e <out>/<site>_<id>.txt."

    def add_arguments(self, parser):
        parser.add_argument("out")
        parser.add_argument("--prompt", default="v1")

    def handle(self, *args, **options):
        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        pv = PromptVersion.objects.get(name="analise", version=options["prompt"])
        (out / "system.txt").write_text(prompt_mod.render_system(pv), encoding="utf-8")
        (out / "schema.json").write_text(json.dumps(pv.output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        for article in SampleArticle.objects.all():
            (out / f"{article.key}.txt").write_text(prompt_mod.render_user(pv, article), encoding="utf-8")
        self.stdout.write(f"{SampleArticle.objects.count()} pedidos em {out}")
