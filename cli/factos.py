#!/usr/bin/env python3
"""CLI do Factos: gestão por agentes (e humanos) sobre a API. Só stdlib.

Ambiente:
    FACTOS_API_URL   URL base da API (omissão: http://localhost:8010/api)
    FACTOS_TOKEN     token do actor (manage.py create_actor <nome> --kind agent)

Saída: JSON estável no stdout (indentado, chaves ordenadas). Erros: JSON no stderr e exit code 1.
Exemplos:
    factos.py entities review --limit 20
    factos.py entities merge 12 --into 7 --dry-run
    factos.py params set quality.success_warn 0.85 --reason "falsos alarmes no JN"
    factos.py health --bucket day
    factos.py api GET /articles/?status=failed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

API_URL = os.environ.get("FACTOS_API_URL", "http://localhost:8010/api").rstrip("/")
TOKEN = os.environ.get("FACTOS_TOKEN", "")
TIMEOUT = float(os.environ.get("FACTOS_TIMEOUT", "60"))


class CliError(Exception):
    def __init__(self, message: str, status: int | None = None, body=None):
        super().__init__(message)
        self.status, self.body = status, body


def out(data) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def fail(message: str, status: int | None = None, body=None) -> None:
    json.dump({"error": message, "status": status, "body": body}, sys.stderr, ensure_ascii=False, indent=2)
    sys.stderr.write("\n")
    sys.exit(1)


def request(method: str, path: str, body=None, params: dict | None = None, idempotency_key: str | None = None):
    path = path if path.startswith("/") else "/" + path
    url = API_URL + path
    q = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    if q:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Token {TOKEN}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if method == "POST":
        headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {"status": resp.status}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw.decode(errors="replace")[:2000]
        raise CliError(f"HTTP {exc.code} em {method} {path}", exc.code, parsed) from None
    except urllib.error.URLError as exc:
        raise CliError(f"Sem ligação a {API_URL}: {exc.reason}") from None
    except (OSError, TimeoutError) as exc:   # ligação cortada, timeout
        raise CliError(f"Erro de rede em {method} {path}: {exc}") from None


def parse_value(raw: str):
    """Valor de um parâmetro: JSON quando possível (0.85, true, [1,2]), senão texto."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# Comandos -------------------------------------------------------------------------------------------------------

def paging(a) -> dict:
    return {"limit": a.limit, "offset": a.offset}


def cmd_sites(a):
    if a.action == "show":
        return request("GET", f"/sites/{a.id}/")
    return request("GET", "/sites/", params=paging(a))


def cmd_entrypoints(a):
    if a.action == "run":
        return request("POST", f"/entrypoints/{a.id}/run/", idempotency_key=a.idempotency_key)
    if a.action == "runs":
        return request("GET", "/discovery-runs/", params={**paging(a), "entrypoint": a.id, "site": a.site})
    return request("GET", "/entrypoints/", params={**paging(a), "site": a.site})


def cmd_articles(a):
    if a.action == "show":
        return request("GET", f"/articles/{a.id}/")
    if a.action == "versions":
        if a.number:
            return request("GET", f"/articles/{a.id}/versions/{a.number}/")
        return request("GET", f"/articles/{a.id}/versions/")
    if a.action == "refetch":
        return request("POST", f"/articles/{a.id}/refetch/", idempotency_key=a.idempotency_key)
    if a.action == "ingest":
        return request("POST", "/articles/ingest/", {"url": a.url, "site": a.site},
                       idempotency_key=a.idempotency_key)
    return request("GET", "/articles/", params={
        **paging(a), "site": a.site, "status": a.status, "piece_type": a.piece_type, "topic": a.topic,
        "entity": a.entity, "q": a.q, "published_after": a.published_after,
        "published_before": a.published_before})


def cmd_fetches(a):
    return request("GET", "/fetches/", params={**paging(a), "site": a.site, "outcome": a.outcome,
                                               "quality_ok": a.quality_ok, "reason": a.reason, "since": a.since})


def cmd_failures(a):
    if a.action == "retry":
        return request("POST", f"/failures/{a.id}/retry/", idempotency_key=a.idempotency_key)
    return request("GET", "/failures/", params={**paging(a), "site": a.site, "status": a.status, "kind": a.kind})


def cmd_params(a):
    if a.action == "get":
        return request("GET", f"/parameters/{a.key}/")
    if a.action == "set":
        if not a.reason:
            raise CliError("--reason é obrigatório para mudar um parâmetro")
        return request("PATCH", f"/parameters/{a.key}/", {"value": parse_value(a.value), "reason": a.reason})
    return request("GET", "/parameters/", params={"limit": a.limit or 500, "offset": a.offset,
                                                  "key__startswith": a.prefix})


def _merge(kind: str, a):
    body = {"into": a.into, "dry_run": a.dry_run}
    if a.reason:
        body["reason"] = a.reason
    return request("POST", f"/{kind}/{a.id}/merge/", body, idempotency_key=a.idempotency_key)


def cmd_entities(a):
    if a.action == "show":
        return request("GET", f"/entities/{a.id}/")
    if a.action == "review":
        return request("GET", "/entities/review-queue/", params={**paging(a), "type": a.type})
    if a.action == "merge":
        return _merge("entities", a)
    if a.action == "update":
        return request("PATCH", f"/entities/{a.id}/", json.loads(a.json))
    if a.action == "alias":
        if a.alias_action == "add":
            return request("POST", f"/entities/{a.id}/aliases/", {"alias": a.alias},
                           idempotency_key=a.idempotency_key)
        return request("DELETE", f"/entities/{a.id}/aliases/{a.alias_id}/")
    return request("GET", "/entities/", params={**paging(a), "type": a.type, "status": a.status, "q": a.q})


def cmd_topics(a):
    if a.action == "show":
        return request("GET", f"/topics/{a.id}/")
    if a.action == "hot":
        return request("GET", "/topics/hot/", params={"limit": a.limit})
    if a.action == "review":
        return request("GET", "/topics/review-queue/", params={**paging(a), "kind": a.kind})
    if a.action == "merge":
        return _merge("topics", a)
    if a.action == "update":
        return request("PATCH", f"/topics/{a.id}/", json.loads(a.json))
    return request("GET", "/topics/", params={**paging(a), "status": a.status, "kind": a.kind,
                                              "parent": a.parent, "q": a.q})


def cmd_analyses(a):
    if a.action == "show":
        return request("GET", f"/analyses/{a.id}/")
    if a.action == "run":
        return request("POST", f"/versions/{a.id}/analyze/", idempotency_key=a.idempotency_key)
    return request("GET", "/analyses/", params={**paging(a), "status": a.status, "provider": a.provider,
                                                "model": a.model, "article": a.article})


def cmd_clusters(a):
    if a.id:
        return request("GET", f"/duplicates/clusters/{a.id}/")
    return request("GET", "/duplicates/clusters/", params={**paging(a), "article": a.article})


def cmd_stats(a):
    return request("GET", "/stats/")


def cmd_health(a):
    return request("GET", "/stats/crawl-health/", params={"site": a.site, "bucket": a.bucket, "since": a.since})


def cmd_audit(a):
    return request("GET", "/audit/", params={**paging(a), "actor": a.actor, "action": a.action_filter,
                                             "object_type": a.object_type, "object_id": a.object_id,
                                             "since": a.since})


def cmd_api(a):
    body = json.loads(a.json) if a.json else None
    return request(a.method.upper(), a.path, body, idempotency_key=a.idempotency_key)


# Argumentos -----------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factos", description="CLI do Factos (saída JSON).")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    def pg(sp):
        sp.add_argument("--limit", type=int)
        sp.add_argument("--offset", type=int)
        return sp

    def idem(sp):
        sp.add_argument("--idempotency-key", help="Chave para repetir sem efeitos duplicados (omissão: uuid)")
        return sp

    def merge_args(sp):
        sp.add_argument("--into", type=int, required=True, help="ID do destino")
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                       help="Só mostra o impacto (omissão)")
        g.add_argument("--execute", dest="dry_run", action="store_false", help="Executa a fusão")
        sp.add_argument("--reason")
        idem(sp)

    s = add("sites", cmd_sites, "Sites")
    s.add_argument("action", nargs="?", default="list", choices=["list", "show"])
    s.add_argument("id", nargs="?")
    pg(s)

    s = add("entrypoints", cmd_entrypoints, "Pontos de entrada da descoberta")
    s.add_argument("action", nargs="?", default="list", choices=["list", "run", "runs"])
    s.add_argument("id", nargs="?", type=int)
    s.add_argument("--site")
    pg(idem(s))

    s = add("articles", cmd_articles, "Notícias")
    s.add_argument("action", nargs="?", default="list", choices=["list", "show", "versions", "refetch", "ingest"])
    s.add_argument("id", nargs="?", type=int)
    s.add_argument("number", nargs="?", type=int, help="versions: nº da versão")
    for f in ("site", "status", "piece_type", "topic", "entity", "q", "published_after", "published_before",
              "url"):
        s.add_argument(f"--{f.replace('_', '-')}", dest=f)
    pg(idem(s))

    s = add("fetches", cmd_fetches, "Leituras HTTP")
    for f in ("site", "outcome", "quality_ok", "reason", "since"):
        s.add_argument(f"--{f.replace('_', '-')}", dest=f)
    pg(s)

    s = add("failures", cmd_failures, "Falhas técnicas")
    s.add_argument("action", nargs="?", default="list", choices=["list", "retry"])
    s.add_argument("id", nargs="?", type=int)
    for f in ("site", "status", "kind"):
        s.add_argument(f"--{f}")
    pg(idem(s))

    s = add("params", cmd_params, "Parâmetros (limiares, tempos, pesos)")
    s.add_argument("action", nargs="?", default="list", choices=["list", "get", "set"])
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?", help="set: valor JSON (0.85, true, [60, 300]) ou texto")
    s.add_argument("--reason", help="set: obrigatório, fica na auditoria")
    s.add_argument("--prefix", help="list: só chaves com este prefixo (ex.: quality.)")
    pg(s)

    s = add("entities", cmd_entities, "Entidades")
    es = s.add_subparsers(dest="action")
    es.required = False
    s.set_defaults(action="list", type=None, status=None, q=None, limit=None, offset=None)
    x = pg(es.add_parser("list"))
    x.add_argument("--type"), x.add_argument("--status"), x.add_argument("--q")
    x = es.add_parser("show")
    x.add_argument("id", type=int)
    x = pg(es.add_parser("review", help="Fila por rever (mais mencionadas primeiro)"))
    x.add_argument("--type")
    x = es.add_parser("merge", help="Funde ID em --into (dry-run por omissão; --execute para fundir)")
    x.add_argument("id", type=int)
    merge_args(x)
    x = es.add_parser("update", help="PATCH com JSON (ex.: '{\"status\": \"active\"}')")
    x.add_argument("id", type=int)
    x.add_argument("json")
    x = es.add_parser("alias", help="alias add ID ALIAS | alias remove ID ALIAS_ID")
    x.add_argument("alias_action", choices=["add", "remove"])
    x.add_argument("id", type=int)
    x.add_argument("alias", nargs="?")
    x.add_argument("alias_id", nargs="?", type=int)
    idem(x)

    s = add("topics", cmd_topics, "Temas")
    ts = s.add_subparsers(dest="action")
    ts.required = False
    s.set_defaults(action="list", status=None, kind=None, parent=None, q=None, limit=None, offset=None)
    x = pg(ts.add_parser("list"))
    x.add_argument("--status"), x.add_argument("--kind"), x.add_argument("--parent"), x.add_argument("--q")
    x = ts.add_parser("show")
    x.add_argument("id", type=int)
    x = ts.add_parser("hot")
    x.add_argument("--limit", type=int)
    x = pg(ts.add_parser("review"))
    x.add_argument("--kind")
    x = ts.add_parser("merge")
    x.add_argument("id", type=int)
    merge_args(x)
    x = ts.add_parser("update")
    x.add_argument("id", type=int)
    x.add_argument("json")

    s = add("analyses", cmd_analyses, "Análises LLM")
    s.add_argument("action", nargs="?", default="list", choices=["list", "show", "run"])
    s.add_argument("id", nargs="?", type=int, help="show: ID da análise; run: ID da versão")
    for f in ("status", "provider", "model", "article"):
        s.add_argument(f"--{f}")
    pg(idem(s))

    s = add("clusters", cmd_clusters, "Clusters de duplicados")
    s.add_argument("id", nargs="?", type=int)
    s.add_argument("--article", type=int)
    pg(s)

    add("stats", cmd_stats, "Estatísticas gerais")

    s = add("health", cmd_health, "Fiabilidade do crawl (ok | warn | alert por site)")
    s.add_argument("--site")
    s.add_argument("--bucket", choices=["hour", "day"])
    s.add_argument("--since", help="ISO 8601 ou relativo (48h, 30d)")

    s = add("audit", cmd_audit, "Auditoria das escritas")
    s.add_argument("--actor"), s.add_argument("--action", dest="action_filter")
    s.add_argument("--object-type", dest="object_type"), s.add_argument("--object-id", dest="object_id")
    s.add_argument("--since")
    pg(s)

    s = add("api", cmd_api, "Pedido genérico: api METHOD PATH [JSON]")
    s.add_argument("method", choices=["GET", "POST", "PATCH", "PUT", "DELETE", "get", "post", "patch", "put",
                                      "delete"])
    s.add_argument("path", help="Relativo a FACTOS_API_URL (ex.: /topics/?status=por_rever)")
    s.add_argument("json", nargs="?")
    idem(s)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if not TOKEN and args.cmd != "api":
        fail("FACTOS_TOKEN não definido (manage.py create_actor <nome> --kind agent)")
    try:
        if args.cmd == "entities" and args.action == "alias":
            if args.alias_action == "add" and not args.alias:
                raise CliError("alias add ID ALIAS")
            if args.alias_action == "remove":
                if args.alias_id is None and args.alias and args.alias.isdigit():
                    args.alias_id = int(args.alias)
                if args.alias_id is None:
                    raise CliError("alias remove ID ALIAS_ID")
        out(args.fn(args))
    except CliError as exc:
        fail(str(exc), exc.status, exc.body)
    except json.JSONDecodeError as exc:
        fail(f"JSON inválido: {exc}")


if __name__ == "__main__":
    main()
