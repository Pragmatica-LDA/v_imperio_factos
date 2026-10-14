"""Resolução de entidades (aliases normalizados, tipos, fusões, meios)."""

from __future__ import annotations

import pytest

from entities.models import Entity, EntityAlias
from entities.normalize import normalize
from entities.resolve import map_type, resolve
from sources.models import Site

pytestmark = pytest.mark.django_db


def _entity(name, type_="pessoa", status="active", aliases=()):
    e = Entity.objects.create(canonical_name=name, type=type_, status=status)
    for a in (name, *aliases):
        EntityAlias.objects.get_or_create(entity=e, normalized=normalize(a), defaults={"alias": a})
    return e


def test_map_type():
    assert map_type("meio_comunicacao") == "meio"
    assert map_type("governo") == "governo" and map_type("empresa") == "empresa"
    assert map_type("desconhecido") == "outro"


def test_none_creates_por_rever(db):
    e, dbg = resolve("PSP", "Polícia de Segurança Pública", "instituicao", is_public=True, analysis_id=3)
    assert e.status == "por_rever" and e.canonical_name == "Polícia de Segurança Pública"
    assert set(e.aliases.values_list("normalized", flat=True)) == {"psp", "policia de seguranca publica"}
    assert e.debug["created_by_analysis"] == 3 and "sem correspondência" in dbg["decision"]
    again, _ = resolve("Polícia de Segurança Pública", None, "instituicao")
    assert again == e


def test_accent_insensitive_and_type_group(db):
    psd = _entity("Partido Social Democrata", "partido", aliases=("PSD",))
    e, dbg = resolve("psd", "P.S.D.", "organizacao")   # tipo diferente mas do mesmo grupo (colectivas)
    assert e == psd and "grupo" in dbg["decision"]
    pessoa, _ = resolve("PSD", "PSD", "pessoa")        # pessoa não liga a um partido
    assert pessoa != psd and pessoa.status == "por_rever"


def test_follows_merged_into(db):
    target = _entity("Luís Montenegro")
    old = _entity("Luis Montenegro Esteves", status="merged", aliases=("Montenegro",))
    old.merged_into = target
    old.save()
    e, _ = resolve("Montenegro", "Montenegro", "pessoa")
    assert e == target


def test_media_links_to_site_entity(seeded):
    jn = Site.objects.get(slug="jn")
    e, dbg = resolve("jn.pt", "JN", "meio")
    assert e.pk == jn.entity_id and dbg["site"] == "jn"
    e, _ = resolve("Jornal de Notícias", None, "meio")
    assert e.pk == jn.entity_id


def test_create_false_does_not_create(db):
    e, dbg = resolve("Ninguém", None, "outro", create=False)
    assert e is None and not Entity.objects.exists()
