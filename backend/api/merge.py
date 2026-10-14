"""Fusão de entidades e de temas, com dry-run (impacto sem alterações) e execução numa transacção."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from analysis.models import CitedSource
from crawl.models import Article
from entities.models import ArticleEntity, Entity, EntityAlias
from entities.normalize import normalize
from sources.models import Site
from topics.models import ArticleTopic, Edition, Topic, TopicTemperature


class MergeError(ValueError):
    pass


def _check(src, dst, label: str) -> None:
    if src.pk == dst.pk:
        raise MergeError(f"Não se funde {label} consigo próprio.")
    if src.status == "merged":
        raise MergeError(f"A origem já está fundida (em {src.merged_into_id}).")
    if dst.status == "merged":
        raise MergeError(f"O destino está fundido (em {dst.merged_into_id}); usa o destino final.")


# Entidades ------------------------------------------------------------------------------------------------------

def entity_impact(src: Entity, dst: Entity) -> dict:
    _check(src, dst, "uma entidade")
    dst_norms = set(EntityAlias.objects.filter(entity=dst).values_list("normalized", flat=True))
    src_aliases = list(EntityAlias.objects.filter(entity=src).values_list("normalized", flat=True))
    return {
        "source": {"id": src.pk, "name": src.canonical_name, "type": src.type, "status": src.status},
        "target": {"id": dst.pk, "name": dst.canonical_name, "type": dst.type, "status": dst.status},
        "type_mismatch": src.type != dst.type,
        "mentions": ArticleEntity.objects.filter(entity=src).count(),
        "aliases": len(src_aliases),
        "aliases_duplicated": sum(1 for n in src_aliases if n in dst_norms),
        "cited_sources": CitedSource.objects.filter(entity=src).count(),
        "sites": Site.objects.filter(entity=src).count(),
        "children": Entity.objects.filter(parent=src).exclude(pk=dst.pk).count(),
        "merged_from": Entity.objects.filter(merged_into=src).count(),
    }


def merge_entities(src: Entity, dst: Entity) -> dict:
    with transaction.atomic():
        src = Entity.objects.select_for_update().get(pk=src.pk)
        dst = Entity.objects.select_for_update().get(pk=dst.pk)
        impact = entity_impact(src, dst)
        ArticleEntity.objects.filter(entity=src).update(entity=dst)
        dst_norms = set(EntityAlias.objects.filter(entity=dst).values_list("normalized", flat=True))
        for a in EntityAlias.objects.filter(entity=src):
            if a.normalized in dst_norms:
                a.delete()
            else:
                a.entity = dst
                a.save(update_fields=["entity"])
                dst_norms.add(a.normalized)
        # O nome canónico da origem passa a alias do destino.
        n = normalize(src.canonical_name)
        if n and n not in dst_norms:
            EntityAlias.objects.create(entity=dst, alias=src.canonical_name, normalized=n)
        CitedSource.objects.filter(entity=src).update(entity=dst)
        Site.objects.filter(entity=src).update(entity=dst)
        if dst.parent_id == src.pk:
            dst.parent_id = src.parent_id
            dst.save(update_fields=["parent"])
        Entity.objects.filter(parent=src).exclude(pk=dst.pk).update(parent=dst)
        Entity.objects.filter(merged_into=src).update(merged_into=dst)
        src.status, src.merged_into = "merged", dst
        src.debug = {**(src.debug or {}), "merged": {"into": dst.pk, "at": timezone.now().isoformat()}}
        src.save(update_fields=["status", "merged_into", "debug"])
    return impact


# Temas ----------------------------------------------------------------------------------------------------------

def topic_impact(src: Topic, dst: Topic) -> dict:
    _check(src, dst, "um tema")
    dst_labels = set(Edition.objects.filter(topic=dst).values_list("label", flat=True))
    src_labels = list(Edition.objects.filter(topic=src).values_list("label", flat=True))
    return {
        "source": {"id": src.pk, "name": src.name, "kind": src.kind, "status": src.status,
                   "temperature": src.temperature},
        "target": {"id": dst.pk, "name": dst.name, "kind": dst.kind, "status": dst.status,
                   "temperature": dst.temperature},
        "article_links": ArticleTopic.objects.filter(topic=src).count(),
        "editions": len(src_labels),
        "editions_merged": sum(1 for lbl in src_labels if lbl in dst_labels),
        "children": Topic.objects.filter(parent=src).exclude(pk=dst.pk).count(),
        "temperature_history": TopicTemperature.objects.filter(topic=src).count(),
        "articles_revisit_topic": Article.objects.filter(revisit_topic=src).count(),
        "merged_from": Topic.objects.filter(merged_into=src).count(),
    }


def merge_topics(src: Topic, dst: Topic) -> dict:
    with transaction.atomic():
        src = Topic.objects.select_for_update().get(pk=src.pk)
        dst = Topic.objects.select_for_update().get(pk=dst.pk)
        impact = topic_impact(src, dst)
        dst_editions = {e.label: e for e in Edition.objects.filter(topic=dst)}
        for e in Edition.objects.filter(topic=src):
            same = dst_editions.get(e.label)
            if same:
                ArticleTopic.objects.filter(edition=e).update(edition=same)
                e.delete()
            else:
                e.topic = dst
                e.save(update_fields=["topic"])
        ArticleTopic.objects.filter(topic=src).update(topic=dst)
        if dst.parent_id == src.pk:
            dst.parent_id = src.parent_id
        Topic.objects.filter(parent=src).exclude(pk=dst.pk).update(parent=dst)
        Topic.objects.filter(merged_into=src).update(merged_into=dst)
        TopicTemperature.objects.filter(topic=src).update(topic=dst)
        Article.objects.filter(revisit_topic=src).update(revisit_topic=dst)
        # Aproximação até ao próximo recálculo (topics.tasks.recompute_temperature): a temperatura é uma soma.
        dst.temperature = round(dst.temperature + src.temperature, 4)
        dst.save(update_fields=["parent", "temperature"])
        src.status, src.merged_into, src.temperature = "merged", dst, 0.0
        src.debug = {**(src.debug or {}), "merged": {"into": dst.pk, "at": timezone.now().isoformat()}}
        src.save(update_fields=["status", "merged_into", "temperature", "debug"])
    return impact
