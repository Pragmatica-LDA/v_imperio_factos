"""Corre modelos sobre artigos, grava os resultados e pontua-os contra a baseline."""

from __future__ import annotations

import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from django.utils import timezone

from benchmark.llm import ProviderError, get_provider, parse_json
from benchmark.models import BenchmarkRun, BenchmarkScore, BenchResult

from . import prompt as prompt_mod
from .schema import validate
from .scoring import score


REPAIR_TEMPLATE = (
    "\n\n---\nA tua resposta anterior a este pedido não passou a validação do schema:\n{errors}\n"
    "Devolve de novo a análise completa, em JSON válido segundo o schema."
)


def degenerate(output: dict, article) -> str | None:
    """Resposta válida no schema mas vazia (visto no Sonnet 5.5: stub com listas vazias e reasoning "x")."""
    if article.word_count >= 100 and not output.get("entities") and not output.get("themes"):
        return "resposta degenerada: sem entidades nem temas num artigo com texto"
    return None


def _attempt(config, system: str, user: str, schema: dict, article) -> dict:
    """Uma chamada ao modelo + leitura e validação do JSON."""
    out = {"output": None, "text": "", "errors": [], "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "meta": {}}
    try:
        result = get_provider(config).analyse(system, user, schema)
    except ProviderError as exc:
        out["errors"] = [str(exc)]
        out["fatal"] = True
        return out
    except Exception as exc:  # noqa: BLE001 — qualquer falha fica registada e o benchmark continua
        out["errors"] = [f"{type(exc).__name__}: {exc}"]
        out["fatal"] = True
        return out
    out.update(text=result.text, latency_ms=result.latency_ms or 0, tokens_in=result.tokens_in or 0,
               tokens_out=result.tokens_out or 0, meta=result.meta)
    try:
        out["output"] = parse_json(result.text)
    except ValueError as exc:
        out["errors"] = [f"JSON inválido: {exc}"]
        return out
    out["errors"] = validate(out["output"], schema)
    if not out["errors"] and isinstance(out["output"], dict):
        problem = degenerate(out["output"], article)
        if problem:
            out["errors"] = [problem]
    return out


def call_model(config, prompt_version, article) -> dict:
    """Faz o pedido e devolve os campos do BenchResult (sem gravar). Corre em threads.

    Com `params.repair_attempts` > 0 (modelos sem structured outputs garantidos, ex.: Ollama Cloud), uma
    resposta que falha o schema é repetida com os erros. Latência, tokens e custo somam todas as tentativas;
    `provider_meta.repairs` diz quantas foram precisas (0 = válido à primeira).
    """
    system = prompt_mod.render_system(prompt_version)
    user = prompt_mod.render_user(prompt_version, article)
    schema = prompt_version.output_schema
    repairs_allowed = int((config.params or {}).get("repair_attempts", 0))

    attempts = [_attempt(config, system, user, schema, article)]
    while attempts[-1]["errors"] and not attempts[-1].get("fatal") and len(attempts) <= repairs_allowed:
        errors = "\n".join(f"- {e}" for e in attempts[-1]["errors"][:15])
        attempts.append(_attempt(config, system, user + REPAIR_TEMPLATE.format(errors=errors), schema, article))

    last = attempts[-1]
    tokens_in = sum(a["tokens_in"] for a in attempts)
    tokens_out = sum(a["tokens_out"] for a in attempts)
    fields = {
        "output": last["output"],
        "raw_response": last["text"],
        "valid_schema": not last["errors"],
        "error": "" if not last["errors"] else "; ".join(last["errors"][:10]),
        "latency_ms": sum(a["latency_ms"] for a in attempts) or None,
        "tokens_in": tokens_in or None,
        "tokens_out": tokens_out or None,
        "provider_meta": {**last["meta"], "repairs": len(attempts) - 1,
                          "first_errors": attempts[0]["errors"][:5] if len(attempts) > 1 else []},
    }
    if tokens_in or tokens_out:
        fields["cost_usd"] = Decimal(str(round(config.cost(tokens_in, tokens_out), 6)))
    return fields


def score_result(run: BenchmarkRun, result: BenchResult, baseline: BenchResult) -> BenchmarkScore:
    config = run.scoring_config
    candidate = result.output if result.valid_schema else None
    metrics, total, details = score(baseline.output, candidate, config.weights, config.thresholds)
    return BenchmarkScore.objects.update_or_create(
        result=result,
        defaults={"run": run, "baseline_result": baseline, "metrics": metrics, "total": total, "details": details},
    )[0]


def baselines_for(label: str, articles) -> dict[int, BenchResult]:
    qs = BenchResult.objects.filter(is_baseline=True, baseline_label=label, article__in=articles)
    return {r.article_id: r for r in qs}


def run_benchmark(run: BenchmarkRun, log=print) -> BenchmarkRun:
    articles = list(run.articles.all())
    baselines = baselines_for(run.baseline_label, articles)
    missing = [a.key for a in articles if a.id not in baselines]
    if missing:
        log(f"Sem baseline '{run.baseline_label}' para {len(missing)} artigos (ficam de fora): {', '.join(missing)}")
        articles = [a for a in articles if a.id in baselines]

    try:
        for config in run.model_configs.all():
            done_pairs = set(run.results.filter(model_config=config).values_list("article_id", "attempt"))
            jobs = [(article, attempt) for attempt in range(1, run.repeat + 1) for article in articles
                    if (article.id, attempt) not in done_pairs]
            if not jobs:
                log(f"\n== {config.name}: já completo, a saltar")
                continue
            log(f"\n== {config.name} ({config.provider}:{config.model_id}) · {len(jobs)} pedidos · "
                f"concorrência {config.concurrency}")
            with ThreadPoolExecutor(max_workers=max(1, config.concurrency)) as pool:
                futures = {pool.submit(call_model, config, run.prompt_version, a): (a, n) for a, n in jobs}
                for done, future in enumerate(as_completed(futures), 1):
                    article, attempt = futures[future]
                    fields = future.result()
                    result = BenchResult.objects.create(
                        article=article, model_config=config, prompt_version=run.prompt_version, run=run,
                        attempt=attempt, **fields,
                    )
                    s = score_result(run, result, baselines[article.id])
                    status = f"score {s.total:.3f}" if result.valid_schema else f"ERRO {result.error[:120]}"
                    latency = f"{result.latency_ms / 1000:.1f}s" if result.latency_ms else "—"
                    log(f"  [{done}/{len(jobs)}] {article.key} #{attempt} · {latency} · {status}")
        run.summary = summarize(run)
        run.status = BenchmarkRun.STATUS_DONE
    except BaseException:
        run.status = BenchmarkRun.STATUS_FAILED
        run.summary = summarize(run)
        raise
    finally:
        run.finished_at = timezone.now()
        run.save()
    return run


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def summarize(run: BenchmarkRun) -> dict:
    """Agregados por modelo: qualidade (score e métricas), fiabilidade, velocidade e custo."""
    summary = {}
    for config in run.model_configs.all():
        results = list(run.results.filter(model_config=config).select_related("score"))
        if not results:
            continue
        scores = [r.score for r in results if hasattr(r, "score")]
        totals = [s.total for s in scores]
        valid = [r for r in results if r.valid_schema]
        first_try = [r for r in valid if not r.provider_meta.get("repairs")]
        latencies = [r.latency_ms / 1000 for r in results if r.latency_ms]
        tokens_out = [r.tokens_out for r in results if r.tokens_out]
        tokens_in = [r.tokens_in for r in results if r.tokens_in]
        costs = [float(r.cost_usd) for r in results if r.cost_usd is not None]
        tps = [r.provider_meta.get("tokens_per_s") for r in results if r.provider_meta.get("tokens_per_s")]
        if not tps:
            tps = [r.tokens_out / (r.latency_ms / 1000) for r in results if r.tokens_out and r.latency_ms]

        metric_names = sorted({k for s in scores for k in s.metrics})
        metrics = {}
        for name in metric_names:
            values = [s.metrics[name] for s in scores if s.metrics.get(name) is not None]
            metrics[name] = round(statistics.fmean(values), 4) if values else None

        # Variância entre repetições do mesmo artigo (só com --repeat > 1)
        by_article: dict[int, list[float]] = {}
        for r in results:
            if hasattr(r, "score"):
                by_article.setdefault(r.article_id, []).append(r.score.total)
        spreads = [statistics.pstdev(v) for v in by_article.values() if len(v) > 1]

        cost_per_article = statistics.fmean(costs) if costs else None
        summary[config.name] = {
            "provider": config.provider,
            "model_id": config.model_id,
            "n": len(results),
            "valid_rate": round(len(valid) / len(results), 4),
            "valid_first_try_rate": round(len(first_try) / len(results), 4),
            "score_mean": round(statistics.fmean(totals), 4) if totals else None,
            "score_min": round(min(totals), 4) if totals else None,
            "score_std_between_repeats": round(statistics.fmean(spreads), 4) if spreads else None,
            "metrics": metrics,
            "latency_p50_s": round(_percentile(latencies, 0.5), 2) if latencies else None,
            "latency_p95_s": round(_percentile(latencies, 0.95), 2) if latencies else None,
            "tokens_in_mean": round(statistics.fmean(tokens_in)) if tokens_in else None,
            "tokens_out_mean": round(statistics.fmean(tokens_out)) if tokens_out else None,
            "tokens_per_s": round(statistics.fmean(tps), 1) if tps else None,
            "cost_per_article_usd": round(cost_per_article, 6) if cost_per_article is not None else None,
            "cost_per_1000_usd": round(cost_per_article * 1000, 2) if cost_per_article is not None else None,
            "errors": [f"{r.article.key}: {r.error[:200]}" for r in results if r.error][:20],
        }
    return summary
