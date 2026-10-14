"""Serializers da API. Usam fields="__all__"/exclude para tolerar campos novos nos modelos."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from analysis.models import Analysis, CitedSource
from core import parameters
from core.models import AuditLog, Parameter
from crawl.models import ArticleLink, Article, ArticleURL, Fetch, TechnicalFailure, Version
from duplicates.models import Cluster, ClusterMember
from entities.models import ArticleEntity, Entity, EntityAlias
from sources.models import DiscoveryRun, EntryPoint, Site
from topics.models import ArticleTopic, Edition, Topic


# Fontes ---------------------------------------------------------------------------------------------------------

class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = "__all__"


class EntryPointSerializer(serializers.ModelSerializer):
    site_slug = serializers.CharField(source="site.slug", read_only=True)

    class Meta:
        model = EntryPoint
        fields = "__all__"
        read_only_fields = ["last_run_at"]


class DiscoveryRunSerializer(serializers.ModelSerializer):
    site = serializers.CharField(source="entrypoint.site.slug", read_only=True)
    entrypoint_name = serializers.CharField(source="entrypoint.name", read_only=True)

    class Meta:
        model = DiscoveryRun
        fields = "__all__"


# Notícias -------------------------------------------------------------------------------------------------------

class ArticleURLSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleURL
        fields = ["id", "url", "kind", "first_seen_at"]


class VersionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Version
        fields = ["id", "number", "created_at", "change_ratio", "word_count", "fetch"]


class VersionDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Version
        exclude = ["minhash"]


class ArticleListSerializer(serializers.ModelSerializer):
    site = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Article
        fields = ["id", "site", "site_article_id", "canonical_url", "status", "title", "section", "published_at",
                  "access", "piece_type", "agencies", "first_seen_at", "last_fetched_at", "version_count",
                  "change_ratio_total", "next_revisit_at"]


class AnalysisSummarySerializer(serializers.ModelSerializer):
    version_number = serializers.IntegerField(source="version.number", read_only=True)

    class Meta:
        model = Analysis
        fields = ["id", "version", "version_number", "status", "provider", "model", "prompt_version",
                  "piece_type", "summary", "created_at", "finished_at"]


class ArticleDetailSerializer(serializers.ModelSerializer):
    site = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    urls = ArticleURLSerializer(many=True, read_only=True)
    versions = VersionSummarySerializer(many=True, read_only=True)
    latest_analysis = serializers.SerializerMethodField()
    cluster = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = "__all__"

    @extend_schema_field(AnalysisSummarySerializer(allow_null=True))
    def get_latest_analysis(self, obj):
        a = (Analysis.objects.filter(version__article=obj).select_related("version")
             .order_by("-version__number", "-created_at").first())
        return AnalysisSummarySerializer(a).data if a else None

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_cluster(self, obj):
        m = ClusterMember.objects.filter(article=obj).select_related("cluster").first()
        if m is None:
            return None
        c = m.cluster
        return {"id": c.pk, "origin": c.origin, "original": c.original_id, "is_original": m.is_original,
                "similarity": m.similarity, "members": c.members.count()}


class IngestSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=1000)
    site = serializers.SlugField(help_text="Slug do site")


class FetchSerializer(serializers.ModelSerializer):
    site = serializers.CharField(source="article.site.slug", read_only=True)
    article_title = serializers.CharField(source="article.title", read_only=True)

    class Meta:
        model = Fetch
        fields = "__all__"


class ArticleLinkSerializer(serializers.ModelSerializer):
    site = serializers.CharField(source="article.site.slug", read_only=True)
    version_number = serializers.IntegerField(source="version.number", read_only=True)

    class Meta:
        model = ArticleLink
        fields = "__all__"


class FailureSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicalFailure
        fields = "__all__"


# Parâmetros -----------------------------------------------------------------------------------------------------

def _type_name(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number" if isinstance(v, float) else "int"
    return {str: "str", list: "list", dict: "dict"}.get(type(v), type(v).__name__)


class ParameterSerializer(serializers.ModelSerializer):
    default = serializers.SerializerMethodField()
    updated_by = serializers.SlugRelatedField(slug_field="username", read_only=True)
    reason = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                   help_text="Porque se muda o valor (fica na auditoria)")

    class Meta:
        model = Parameter
        fields = ["key", "value", "description", "default", "updated_at", "updated_by", "reason"]
        read_only_fields = ["key", "updated_at"]

    @extend_schema_field(OpenApiTypes.ANY)
    def get_default(self, obj):
        d = parameters.DEFAULTS.get(obj.key)
        return d[0] if d else None

    def validate_value(self, value):
        key = self.instance.key if self.instance else None
        if key in parameters.DEFAULTS:
            default = parameters.DEFAULTS[key][0]
            want, got = _type_name(default), _type_name(value)
            ok = want == got or (want == "number" and got == "int")
            if not ok:
                raise serializers.ValidationError(f"Tipo inválido: esperado {want}, recebido {got}.")
        return value

    def update(self, instance, validated_data):
        validated_data.pop("reason", None)
        return super().update(instance, validated_data)


# Entidades ------------------------------------------------------------------------------------------------------

class EntityAliasSerializer(serializers.ModelSerializer):
    class Meta:
        model = EntityAlias
        fields = ["id", "alias", "normalized"]
        read_only_fields = ["normalized"]


class EntitySerializer(serializers.ModelSerializer):
    aliases = EntityAliasSerializer(many=True, read_only=True)

    class Meta:
        model = Entity
        fields = "__all__"
        read_only_fields = ["merged_into", "created_at"]


class MergeSerializer(serializers.Serializer):
    into = serializers.IntegerField(help_text="ID do destino")
    dry_run = serializers.BooleanField(default=True, help_text="Por omissão só mostra o impacto")
    reason = serializers.CharField(required=False, allow_blank=True)


class AliasCreateSerializer(serializers.Serializer):
    alias = serializers.CharField(max_length=300)


# Temas ----------------------------------------------------------------------------------------------------------

class EditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Edition
        fields = "__all__"
        read_only_fields = ["topic", "temperature"]


class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = "__all__"
        read_only_fields = ["merged_into", "temperature", "temperature_at", "created_at"]


class TopicDetailSerializer(TopicSerializer):
    editions = EditionSerializer(many=True, read_only=True)


# Análises -------------------------------------------------------------------------------------------------------

class CitedSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CitedSource
        exclude = ["analysis"]


class ArticleEntitySerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source="entity.canonical_name", read_only=True)

    class Meta:
        model = ArticleEntity
        exclude = ["analysis"]


class ArticleTopicSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)

    class Meta:
        model = ArticleTopic
        exclude = ["analysis"]


class AnalysisListSerializer(serializers.ModelSerializer):
    article = serializers.IntegerField(source="version.article_id", read_only=True)

    class Meta:
        model = Analysis
        exclude = ["raw_response", "debug"]


class AnalysisDetailSerializer(serializers.ModelSerializer):
    article = serializers.IntegerField(source="version.article_id", read_only=True)
    sources = CitedSourceSerializer(many=True, read_only=True)
    entities = ArticleEntitySerializer(many=True, read_only=True)
    topics = ArticleTopicSerializer(many=True, read_only=True)

    class Meta:
        model = Analysis
        fields = "__all__"


# Duplicados -----------------------------------------------------------------------------------------------------

class ClusterMemberSerializer(serializers.ModelSerializer):
    site = serializers.CharField(source="article.site.slug", read_only=True)
    title = serializers.CharField(source="article.title", read_only=True)

    class Meta:
        model = ClusterMember
        fields = "__all__"


class ClusterSerializer(serializers.ModelSerializer):
    members = ClusterMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Cluster
        fields = "__all__"


# Auditoria ------------------------------------------------------------------------------------------------------

class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = AuditLog
        fields = "__all__"


class TaskQueuedSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    queue = serializers.CharField()
