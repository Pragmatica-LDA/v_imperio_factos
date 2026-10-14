"""Detecção de duplicados (takes da Lusa, comunicados) por MinHash, sem LLM e sem contar para o limite diário.

- Texto: o **corpo** da versão (título e lead mudam de meio para meio e não dizem nada sobre o take); sem corpo,
  `Version.text`. Normalizado (sem acentos, minúsculas) e partido em palavras.
- Shingles de `duplicates.shingle_size` palavras; MinHash de NUM_PERM permutações (a·h + b mod 2^61−1), com h e
  (a, b) tirados do blake2b: determinístico entre processos e máquinas (o `hash()` do Python não é).
  A assinatura fica em `Version.minhash` (inteiros < 2^61, cabem no BigIntegerField).
- Candidatos: a última versão das outras notícias (qualquer site, incluindo o mesmo) com assinatura e data de
  referência (published_at, ou first_seen_at) a ±`duplicates.window_h`.
- Jaccard estimado ≥ `duplicates.threshold`: junta ao cluster do melhor candidato (ou cria um). O original é o
  membro com a data mais antiga; a similaridade de cada membro é contra o original.
- Origem: `lusa` se algum membro tem Lusa nas agências ou a assinatura da Lusa no texto; `agencia` se tem outra
  agência (incluindo "JN/Agências"); senão `desconhecida`.
- Diferenças textuais entre o original e cada membro (difflib, por palavras) no `Cluster.debug`: as réplicas às
  vezes trocam factos (ex.: "abaixo" vs "acima" do valor previsto na lei).
"""

from __future__ import annotations

import difflib
import hashlib
import re
import zlib
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from core import parameters
from crawl.models import Version
from duplicates.models import Cluster, ClusterMember
from entities.normalize import normalize

NUM_PERM = 128          # mudar invalida as assinaturas guardadas: não é parâmetro
MERSENNE = (1 << 61) - 1
CLUSTER_LOCK = zlib.crc32(b"factos.duplicates.cluster")
LUSA_RE = re.compile(r"Agência Lusa|\(Lusa\)|\bà Lusa\b|\bLusa\s*/|/\s*Lusa\b|\bLUSA\b")


def _h64(data: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")


_PERMS = [(_h64(f"a{i}".encode()) % (MERSENNE - 1) + 1, _h64(f"b{i}".encode()) % MERSENNE) for i in range(NUM_PERM)]


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def shingles(words: list[str], k: int) -> set[str]:
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def minhash(sh: set[str]) -> list[int]:
    if not sh:
        return []
    hashes = [_h64(s.encode("utf-8")) for s in sh]
    return [min((a * h + b) % MERSENNE for h in hashes) for a, b in _PERMS]


def similarity(a: list[int] | None, b: list[int] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def version_text(version: Version) -> str:
    body = [(b.get("text") or "").strip() for b in (version.content or {}).get("body") or []]
    body = [t for t in body if t]
    return "\n\n".join(body) if body else (version.text or "")


def signature(version: Version) -> list[int]:
    return minhash(shingles(tokens(version_text(version)), int(parameters.get("duplicates.shingle_size"))))


def _ref(article):
    return article.published_at or article.first_seen_at


# --- Origem e diferenças ----------------------------------------------------------------------------------------

def origin_of(members: list[ClusterMember]) -> tuple[str, dict]:
    evidence = {}
    other = False
    for m in members:
        agencies = [a for a in (m.article.agencies or [])]
        byline = (m.version.content or {}).get("byline_raw") or ""
        if any(a.lower() == "lusa" for a in agencies):
            evidence[m.article_id] = f"agências: {agencies}"
        elif LUSA_RE.search(byline) or LUSA_RE.search(m.version.text or ""):
            match = LUSA_RE.search(byline) or LUSA_RE.search(m.version.text or "")
            evidence[m.article_id] = f"assinatura no texto: {match.group(0)!r}"
        elif agencies:
            other = True
    if evidence:
        return "lusa", {"lusa": evidence}
    return ("agencia" if other else "desconhecida"), {}


def differences(original: Version, member: Version) -> dict:
    a, b = version_text(original).split(), version_text(member).split()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    ctx = int(parameters.get("duplicates.diff_context_words"))
    max_items = int(parameters.get("duplicates.diff_max_items"))
    changes = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "op": tag,
            "original": " ".join(a[i1:i2])[:500],
            "member": " ".join(b[j1:j2])[:500],
            "context": " ".join(a[max(0, i1 - ctx):i1]) + " […] " + " ".join(a[i2:i2 + ctx]),
        })
    return {"word_ratio": round(sm.ratio(), 4), "n_changes": len(changes), "changes": changes[:max_items],
            "truncated": len(changes) > max_items}


# --- Detecção ---------------------------------------------------------------------------------------------------

def detect(version_id: int) -> dict:
    version = Version.objects.select_related("article").get(pk=version_id)
    article = version.article
    min_words = int(parameters.get("duplicates.min_words"))
    if (version.word_count or len(version_text(version).split())) < min_words:
        return {"status": "skipped", "reason": f"menos de {min_words} palavras"}

    sig = signature(version)
    Version.objects.filter(pk=version.pk).update(minhash=sig)
    version.minhash = sig

    ref = _ref(article) or timezone.now()
    window = timedelta(hours=float(parameters.get("duplicates.window_h")))
    threshold = float(parameters.get("duplicates.threshold"))
    lo, hi = ref - window, ref + window
    cands = (Version.objects.filter(minhash__isnull=False, number=F("article__version_count"))
             .exclude(article_id=article.pk)
             .filter(Q(article__published_at__range=(lo, hi))
                     | Q(article__published_at__isnull=True, article__first_seen_at__range=(lo, hi)))
             .select_related("article"))
    scored = sorted(((similarity(sig, c.minhash), c) for c in cands), key=lambda x: -x[0])
    scored_dbg = [{"article_id": c.article_id, "version_id": c.pk, "site_id": c.article.site_id,
                   "similarity": round(s, 4)} for s, c in scored[:20]]
    matches = [(s, c) for s, c in scored if s >= threshold]

    with transaction.atomic():
        with connection.cursor() as cur:   # um cluster de cada vez: evita dois clusters para o mesmo take
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [CLUSTER_LOCK])
        mine = ClusterMember.objects.filter(article=article).select_related("cluster").first()
        if mine is None and not matches:
            return {"status": "no_match", "best": scored_dbg[:3], "threshold": threshold}

        if mine is not None:
            cluster = mine.cluster
            mine.version = version
            mine.save(update_fields=["version"])
        else:
            clustered = ClusterMember.objects.filter(article_id__in=[c.article_id for _, c in matches]) \
                .select_related("cluster")
            by_article = {m.article_id: m for m in clustered}
            best = next((by_article[c.article_id] for _, c in matches if c.article_id in by_article), None)
            if best is not None:
                cluster = best.cluster
            else:
                cluster = Cluster.objects.create(original=article, debug={})
            ClusterMember.objects.create(cluster=cluster, article=article, version=version, similarity=1.0)
        # Notícias que bateram e ainda não têm cluster entram neste.
        for s, c in matches:
            ClusterMember.objects.get_or_create(article=c.article, defaults={
                "cluster": cluster, "version": c, "similarity": s})

        _refresh(cluster)
        dbg = cluster.debug or {}
        dbg.setdefault("detections", {})[str(article.pk)] = {
            "version_id": version.pk, "at": timezone.now().isoformat(), "threshold": threshold,
            "shingle_size": int(parameters.get("duplicates.shingle_size")), "num_perm": NUM_PERM,
            "candidates": scored_dbg, "matched": [c.article_id for _, c in matches],
        }
        cluster.debug = dbg
        cluster.save(update_fields=["debug", "updated_at"])
    return {"status": "clustered", "cluster_id": cluster.pk, "matches": [d for d in scored_dbg
                                                                      if d["similarity"] >= threshold]}


def _refresh(cluster: Cluster) -> None:
    """Recalcula o original (data mais antiga), a similaridade contra ele, a origem e as diferenças."""
    members = list(cluster.members.select_related("article", "version"))
    far = timezone.now() + timedelta(days=36500)
    members.sort(key=lambda m: (_ref(m.article) or far, m.article_id))
    original = members[0]
    for m in members:
        m.is_original = m.pk == original.pk
        if not m.version.minhash:
            m.version.minhash = signature(m.version)
            Version.objects.filter(pk=m.version.pk).update(minhash=m.version.minhash)
        m.similarity = 1.0 if m.is_original else round(similarity(original.version.minhash, m.version.minhash), 4)
    ClusterMember.objects.bulk_update(members, ["is_original", "similarity"])
    origin, odbg = origin_of(members)
    dbg = cluster.debug or {}
    dbg["origin"] = odbg
    dbg["original_rule"] = "data de publicação mais antiga"
    dbg["differences"] = {str(m.article_id): {"vs": original.article_id, **differences(original.version, m.version)}
                          for m in members if not m.is_original}
    cluster.original_id, cluster.origin, cluster.debug = original.article_id, origin, dbg
    cluster.save(update_fields=["original", "origin", "debug", "updated_at"])
