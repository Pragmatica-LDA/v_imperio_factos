"""Duplicados por MinHash com o take real da Lusa (BE/MAI) no Observador e no JN."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from crawl.models import Version
from duplicates import service
from duplicates.models import Cluster, ClusterMember
from tests.test_analysis import JN, OBS, make_version, set_param

pytestmark = pytest.mark.django_db


def test_minhash_is_deterministic_and_estimates_jaccard():
    a = service.shingles("um dois tres quatro cinco seis sete oito nove dez".split(), 3)
    b = service.shingles("um dois tres quatro cinco seis sete oito nove onze".split(), 3)
    assert service.minhash(a) == service.minhash(set(a))
    assert len(service.minhash(a)) == service.NUM_PERM
    assert all(0 <= x < 2 ** 61 for x in service.minhash(a))
    exact = len(a & b) / len(a | b)
    assert abs(service.similarity(service.minhash(a), service.minhash(b)) - exact) < 0.15
    assert service.similarity(service.minhash(a), service.minhash(a)) == 1.0


def test_real_lusa_take_clusters(seeded):
    obs = make_version(*OBS)
    jn = make_version(*JN)
    r1 = service.detect(obs.pk)
    assert r1["status"] == "no_match"   # o JN ainda não tem assinatura
    r2 = service.detect(jn.pk)
    assert r2["status"] == "clustered", r2
    cluster = Cluster.objects.get()
    members = {m.article_id: m for m in cluster.members.all()}
    assert set(members) == {obs.article_id, jn.article_id}
    # O JN publicou primeiro (11:00 vs 11:48 UTC): é o original. Origem Lusa (agências do Observador).
    assert cluster.original_id == jn.article_id and members[jn.article_id].is_original
    assert cluster.origin == "lusa"
    assert str(obs.article_id) in cluster.debug["origin"]["lusa"]
    sim = members[obs.article_id].similarity
    assert sim >= 0.8, sim
    # A diferença factual (abaixo/acima do valor previsto na lei) fica no debug.
    diff = cluster.debug["differences"][str(obs.article_id)]
    assert any(c["original"] == "acima" and c["member"] == "abaixo" for c in diff["changes"]), diff["changes"][:5]
    assert cluster.debug["detections"][str(jn.article_id)]["candidates"][0]["article_id"] == obs.article_id
    assert Version.objects.get(pk=obs.pk).minhash


def test_detect_is_idempotent_and_handles_new_versions(seeded):
    obs, jn = make_version(*OBS), make_version(*JN)
    service.detect(obs.pk)
    service.detect(jn.pk)
    service.detect(jn.pk)
    service.detect(obs.pk)
    assert Cluster.objects.count() == 1 and ClusterMember.objects.count() == 2
    content = copy.deepcopy(obs.content)
    content["body"].append({"kind": "p", "text": "Actualização: o MAI respondeu.", "links": []})
    obs2 = make_version("observador", "", article=obs.article, content=content)
    assert service.detect(obs2.pk)["status"] == "clustered"
    assert ClusterMember.objects.get(article=obs.article).version_id == obs2.pk
    assert Cluster.objects.count() == 1


def test_threshold_window_and_min_words(seeded):
    obs = make_version(*OBS)
    service.detect(obs.pk)
    far = make_version(*JN, published_at=obs.article.published_at + timedelta(hours=100))
    assert service.detect(far.pk)["status"] == "no_match"            # fora da janela de 48 h
    set_param("duplicates.window_h", 200)
    set_param("duplicates.threshold", 0.99)
    assert service.detect(far.pk)["status"] == "no_match"            # limiar acima da similaridade
    set_param("duplicates.min_words", 10_000)
    assert service.detect(far.pk)["status"] == "skipped"
    assert not Cluster.objects.exists()


def test_unrelated_text_does_not_match(seeded):
    obs = make_version(*OBS)
    service.detect(obs.pk)
    content = copy.deepcopy(obs.content)
    content["body"] = [{"kind": "p", "text": " ".join(f"palavra{i} sobre futebol e golos" for i in range(40)),
                        "links": []}]
    content["word_count"] = 200
    other = make_version("jn", "", content=content)
    r = service.detect(other.pk)
    assert r["status"] == "no_match" and r["best"][0]["similarity"] < 0.2


def test_origin_rules():
    class A:  # noqa: D401 — duplos mínimos
        def __init__(self, agencies):
            self.agencies = agencies

    class V:
        def __init__(self, text="", byline=""):
            self.text, self.content = text, {"byline_raw": byline}

    class M:
        def __init__(self, aid, agencies=(), text="", byline=""):
            self.article_id, self.article, self.version = aid, A(list(agencies)), V(text, byline)

    assert service.origin_of([M(1, ["Agências"]), M(2)])[0] == "agencia"
    assert service.origin_of([M(1), M(2, text="disse à Lusa o ministro")])[0] == "lusa"
    assert service.origin_of([M(1, byline="Agência Lusa")])[0] == "lusa"
    assert service.origin_of([M(1, text="a comunidade lusa em França")])[0] == "desconhecida"
