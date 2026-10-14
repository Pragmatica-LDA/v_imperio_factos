"""Cria (sem sobrepor edições) o prompt v1, a ScoringConfig inicial e as ModelConfigs por omissão."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from benchmark.bench import prompt as prompt_mod
from benchmark.bench.schema import OUTPUT_SCHEMA_V1
from benchmark.bench.scoring import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS
from benchmark.llm.openai_provider import OPENAI_DEFAULT_BASE_URL
from benchmark.models import ModelConfig, PromptVersion, ScoringConfig

# Preços em USD por milhão de tokens (input, output). Confirmar nos sites dos fornecedores antes de decidir.
# Anthropic: tabela da skill claude-api (2026-10-06). OpenAI: agregadores (Out 2026), por confirmar em openai.com.
DEFAULT_MODELS = [
    # name, provider, model_id, params, price_in, price_out, concurrency, notes
    # repair_attempts igual em todos (2): uma resposta inválida ou vazia é repetida com os erros, e o custo conta.
    ("claude-code-opus-5-5", "manual", "claude-opus-5-5", {}, 0, 0, 1,
     "Baseline produzida pelo Claude Code (Opus 5.5) com o mesmo prompt e schema, importada à mão."),
    ("opus-5-5", "anthropic", "claude-opus-5-5", {"effort": "medium", "repair_attempts": 2}, 4, 20, 4,
     "Para refazer a baseline via API (bench_run --as-baseline)."),
    ("sonnet-5-5-low", "anthropic", "claude-sonnet-5-5", {"effort": "low", "repair_attempts": 2}, 2, 10, 4,
     "Devolve às vezes um stub vazio (salvaguarda reasoning_extraction): reparações contadas na latência/custo."),
    ("haiku-5-5-low", "anthropic", "claude-haiku-5-5", {"effort": "low", "repair_attempts": 2}, 0.10, 0.50, 4, ""),
    ("haiku-5-5-medium", "anthropic", "claude-haiku-5-5", {"effort": "medium", "repair_attempts": 2}, 0.10, 0.50, 4, ""),
    ("gpt-5-4-mini", "openai", "gpt-5.4-mini", {"reasoning_effort": "low", "repair_attempts": 2}, 0.75, 4.50, 4,
     "Preço de agregadores; confirmar em openai.com/api/pricing."),
    ("gpt-5-4-nano", "openai", "gpt-5.4-nano", {"reasoning_effort": "low", "repair_attempts": 2}, 0.20, 1.25, 4,
     "Preço de agregadores; confirmar em openai.com/api/pricing."),
]


class Command(BaseCommand):
    help = "Semente do benchmark: prompt v1, scoring por omissão e modelos (Anthropic, OpenAI, baseline manual)."

    def add_arguments(self, parser):
        parser.add_argument("--update", action="store_true",
                            help="Sobrepõe preços/parâmetros das ModelConfigs por omissão (o prompt nunca é alterado).")

    def handle(self, *args, **options):
        pv, created = PromptVersion.objects.get_or_create(
            name="analise", version="v1",
            defaults={
                "system_prompt": prompt_mod.SYSTEM_PROMPT_V1,
                "user_template": prompt_mod.USER_TEMPLATE_V1,
                "output_schema": OUTPUT_SCHEMA_V1,
                "taxonomy": prompt_mod.load_taxonomy(),
            },
        )
        self.stdout.write(f"prompt {pv}: {'criado' if created else 'já existia'}")

        sc, created = ScoringConfig.objects.get_or_create(
            name="default-v1", defaults={"weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS},
        )
        self.stdout.write(f"scoring {sc}: {'criado' if created else 'já existia'}")

        for name, provider, model_id, params, p_in, p_out, conc, notes in DEFAULT_MODELS:
            values = {"provider": provider, "model_id": model_id, "params": params, "price_input_per_mtok": p_in,
                      "price_output_per_mtok": p_out, "concurrency": conc, "notes": notes,
                      "base_url": OPENAI_DEFAULT_BASE_URL if provider == "openai" else ""}
            if options["update"]:
                _, created = ModelConfig.objects.update_or_create(name=name, defaults=values)
            else:
                _, created = ModelConfig.objects.get_or_create(name=name, defaults=values)
            self.stdout.write(f"modelo {name}: {'criado' if created else 'já existia'}")
