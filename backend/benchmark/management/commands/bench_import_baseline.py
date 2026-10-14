"""Importa uma baseline produzida fora da API (um <site>_<id>.json por artigo)."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from benchmark.bench.schema import validate
from benchmark.models import BenchResult, ModelConfig, PromptVersion, SampleArticle


class Command(BaseCommand):
    help = "Valida e grava como baseline os JSON de uma pasta. Substitui a baseline existente com a mesma label."

    def add_arguments(self, parser):
        parser.add_argument("dir")
        parser.add_argument("--label", required=True)
        parser.add_argument("--prompt", default="v1")
        parser.add_argument("--model", default="claude-code-opus-5-5", help="ModelConfig (provider manual).")

    def handle(self, *args, **options):
        pv = PromptVersion.objects.get(name="analise", version=options["prompt"])
        config = ModelConfig.objects.get(name=options["model"])
        articles = {a.key: a for a in SampleArticle.objects.all()}
        files = sorted(Path(options["dir"]).glob("*.json"))
        if not files:
            raise CommandError(f"Sem JSON em {options['dir']}")
        ok, bad = 0, []
        for f in files:
            article = articles.get(f.stem)
            if article is None:
                bad.append(f"{f.name}: artigo não está na amostra")
                continue
            output = json.loads(f.read_text(encoding="utf-8"))
            errors = validate(output, pv.output_schema)
            if errors:
                bad.append(f"{f.name}: {'; '.join(errors[:5])}")
                continue
            BenchResult.objects.update_or_create(
                article=article, is_baseline=True, baseline_label=options["label"],
                defaults={"model_config": config, "prompt_version": pv, "output": output,
                          "raw_response": json.dumps(output, ensure_ascii=False), "valid_schema": True, "error": ""},
            )
            ok += 1
        self.stdout.write(f"baseline '{options['label']}': {ok} artigos importados")
        for b in bad:
            self.stdout.write(self.style.ERROR(f"  {b}"))
        missing = sorted(set(articles) - {f.stem for f in files})
        if missing:
            self.stdout.write(f"  artigos da amostra sem baseline: {', '.join(missing)}")
