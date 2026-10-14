"""Relatório Markdown de um BenchmarkRun (por omissão o último)."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand

from benchmark.bench.report import render
from benchmark.bench.runner import summarize
from benchmark.models import BenchmarkRun


class Command(BaseCommand):
    help = "bench_report [RUN_ID] [--out ficheiro.md] [--recompute]"

    def add_arguments(self, parser):
        parser.add_argument("run_id", nargs="?", type=int)
        parser.add_argument("--out")
        parser.add_argument("--worst", type=int, default=5)
        parser.add_argument("--recompute", action="store_true", help="Recalcula os agregados do run.")

    def handle(self, *args, **options):
        run = BenchmarkRun.objects.get(pk=options["run_id"]) if options["run_id"] else BenchmarkRun.objects.first()
        if options["recompute"]:
            run.summary = summarize(run)
            run.save(update_fields=["summary"])
        text = render(run, worst=options["worst"])
        if options["out"]:
            Path(options["out"]).write_text(text, encoding="utf-8")
            self.stdout.write(f"→ {options['out']}")
        else:
            self.stdout.write(text)
