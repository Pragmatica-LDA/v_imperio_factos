"""Corre modelos sobre a amostra e pontua contra uma baseline (ou gera uma baseline nova via API)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand, CommandError

from benchmark.bench.report import render
from benchmark.bench.runner import call_model, run_benchmark
from benchmark.models import BenchmarkRun, BenchResult, ModelConfig, PromptVersion, SampleArticle, ScoringConfig


class Command(BaseCommand):
    help = "bench_run --models a,b --baseline LABEL [--articles k1,k2] [--repeat N]  |  --as-baseline LABEL --models x"

    def add_arguments(self, parser):
        parser.add_argument("--models", help="Nomes das ModelConfigs separados por vírgula (omissão: todas as activas).")
        parser.add_argument("--baseline", help="Label da baseline contra a qual pontuar.")
        parser.add_argument("--as-baseline", metavar="LABEL", help="Grava os resultados de UM modelo como baseline nova.")
        parser.add_argument("--prompt", default="v1")
        parser.add_argument("--articles", help="Chaves <site>_<id> separadas por vírgula (omissão: toda a amostra).")
        parser.add_argument("--repeat", type=int, default=1)
        parser.add_argument("--notes", default="")
        parser.add_argument("--resume", type=int, metavar="RUN_ID",
                            help="Continua um run: corre só os pares (modelo, artigo) em falta dos --models indicados. "
                                 "Os modelos do run que não estão em --models e não têm resultados saem do run.")

    def handle(self, *args, **options):
        pv = PromptVersion.objects.get(name="analise", version=options["prompt"])
        if options["models"]:
            names = [n.strip() for n in options["models"].split(",") if n.strip()]
            configs = list(ModelConfig.objects.filter(name__in=names))
            unknown = set(names) - {c.name for c in configs}
            if unknown:
                raise CommandError(f"ModelConfigs desconhecidas: {', '.join(sorted(unknown))} (ver bench_models --list)")
        else:
            configs = list(ModelConfig.objects.filter(active=True).exclude(provider=ModelConfig.PROVIDER_MANUAL))
        articles = list(SampleArticle.objects.all())
        if options["articles"]:
            keys = {k.strip() for k in options["articles"].split(",")}
            articles = [a for a in articles if a.key in keys]
        if not articles:
            raise CommandError("Sem artigos (bench_import_articles).")

        if options["resume"]:
            return self._resume(options["resume"], configs)
        if options["as_baseline"]:
            return self._as_baseline(options["as_baseline"], configs, pv, articles)
        if not options["baseline"]:
            raise CommandError("Indica --baseline LABEL (ou --as-baseline).")
        if not BenchResult.objects.filter(is_baseline=True, baseline_label=options["baseline"]).exists():
            raise CommandError(f"Baseline '{options['baseline']}' não existe.")

        run = BenchmarkRun.objects.create(baseline_label=options["baseline"], prompt_version=pv,
                                          scoring_config=ScoringConfig.current(), repeat=options["repeat"],
                                          notes=options["notes"])
        run.model_configs.set(configs)
        run.articles.set(articles)
        self.stdout.write(f"run {run.pk}: {len(configs)} modelos × {len(articles)} artigos × {options['repeat']}")
        run_benchmark(run, log=self.stdout.write)
        self.stdout.write("\n" + render(run))

    def _as_baseline(self, label, configs, pv, articles):
        if len(configs) != 1:
            raise CommandError("--as-baseline aceita exactamente um modelo.")
        config = configs[0]
        with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as pool:
            results = list(pool.map(lambda a: (a, call_model(config, pv, a)), articles))
        for article, fields in results:
            if not fields["valid_schema"]:
                self.stdout.write(self.style.ERROR(f"  {article.key}: {fields['error'][:200]} (não gravado)"))
                continue
            BenchResult.objects.update_or_create(
                article=article, is_baseline=True, baseline_label=label,
                defaults={"model_config": config, "prompt_version": pv, **fields},
            )
            self.stdout.write(f"  {article.key}: ok")

    def _resume(self, run_id, configs):
        run = BenchmarkRun.objects.get(pk=run_id)
        with_results = set(run.results.values_list("model_config_id", flat=True))
        keep = [c for c in run.model_configs.all() if c.id in with_results]
        run.model_configs.set({*keep, *configs})
        run.status = BenchmarkRun.STATUS_RUNNING
        run.save(update_fields=["status"])
        self.stdout.write(f"run {run.pk} retomado: {', '.join(c.name for c in configs)}")
        run_benchmark(run, log=self.stdout.write)
        self.stdout.write("\n" + render(run))
