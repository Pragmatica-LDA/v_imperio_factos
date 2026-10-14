"""Relatório em Markdown de um BenchmarkRun."""

from __future__ import annotations

from benchmark.models import BenchmarkRun

METRIC_LABELS = {
    "piece_type": "tipo",
    "entities_f1": "entid.",
    "entity_type": "tipo ent.",
    "entity_public": "púb.",
    "entity_roles": "papéis",
    "entity_sentiment": "sentim.",
    "sources_f1": "fontes",
    "source_types": "tipos fonte",
    "themes": "temas",
    "theme_edition": "edição",
    "locations_f1": "locais",
    "ai_indicator": "IA",
}


def _fmt(value, digits=3, suffix=""):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def pareto(summary: dict) -> set[str]:
    """Modelos não dominados em (score ↑, latência p50 ↓, custo ↓)."""
    rows = {k: v for k, v in summary.items() if v.get("score_mean") is not None}

    def key(v):
        return v["score_mean"], -(v.get("latency_p50_s") or 1e9), -(v.get("cost_per_article_usd") or 0.0)

    front = set()
    for name, v in rows.items():
        kv = key(v)
        dominated = any(
            all(a >= b for a, b in zip(key(o), kv)) and any(a > b for a, b in zip(key(o), kv))
            for other, o in rows.items() if other != name
        )
        if not dominated:
            front.add(name)
    return front


def render(run: BenchmarkRun, worst: int = 5) -> str:
    summary = run.summary
    front = pareto(summary)
    ordered = sorted(summary.items(), key=lambda kv: kv[1].get("score_mean") or 0, reverse=True)
    lines = [
        f"# Benchmark {run.pk} · baseline `{run.baseline_label}` · prompt {run.prompt_version}",
        "",
        f"{run.articles.count()} artigos · repetições: {run.repeat} · scoring `{run.scoring_config.name}` · "
        f"estado: {run.status} · {run.started_at:%Y-%m-%d %H:%M}",
        "",
        "## Resumo",
        "",
        "| modelo | score | mín | válidos | à 1.ª | p50 | p95 | tok/s | tok in/out | $/artigo | $/1000 | Pareto |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, v in ordered:
        lines.append(
            f"| {name} | {_fmt(v['score_mean'])} | {_fmt(v['score_min'])} | {_fmt(v['valid_rate'] * 100, 0, '%')} "
            f"| {_fmt(v.get('valid_first_try_rate', 0) * 100, 0, '%')} "
            f"| {_fmt(v['latency_p50_s'], 1, 's')} | {_fmt(v['latency_p95_s'], 1, 's')} | {_fmt(v['tokens_per_s'], 0)} "
            f"| {_fmt(v['tokens_in_mean'])}/{_fmt(v['tokens_out_mean'])} | {_fmt(v['cost_per_article_usd'], 5)} "
            f"| {_fmt(v['cost_per_1000_usd'], 2)} | {'★' if name in front else ''} |"
        )

    metric_names = [m for m in METRIC_LABELS if any(m in v["metrics"] for _, v in ordered)]
    lines += [
        "",
        "## Score por métrica (0–1, vs baseline)",
        "",
        "| modelo | " + " | ".join(METRIC_LABELS[m] for m in metric_names) + " |",
        "|---|" + "---|" * len(metric_names),
    ]
    for name, v in ordered:
        lines.append(f"| {name} | " + " | ".join(_fmt(v["metrics"].get(m), 2) for m in metric_names) + " |")

    lines += ["", f"## Piores artigos por modelo (top {worst})", ""]
    for name, _ in ordered:
        scores = run.scores.filter(result__model_config__name=name).select_related("result__article").order_by("total")[:worst]
        lines.append(f"**{name}**")
        for s in scores:
            ent = s.details.get("entities", {})
            notes = []
            if ent.get("missing"):
                notes.append(f"faltam: {', '.join(ent['missing'][:5])}")
            if ent.get("extra"):
                notes.append(f"a mais: {', '.join(ent['extra'][:5])}")
            if s.result.error:
                notes.append(f"erro: {s.result.error[:120]}")
            lines.append(f"- {s.result.article.key} · {s.total:.3f} · {'; '.join(notes) or '—'}")
        lines.append("")

    errors = [(name, v["errors"]) for name, v in ordered if v.get("errors")]
    if errors:
        lines += ["## Erros", ""]
        for name, errs in errors:
            lines.append(f"**{name}**")
            lines += [f"- {e}" for e in errs]
            lines.append("")
    return "\n".join(lines)
