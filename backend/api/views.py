"""Viewsets da API do Factos. Todas as escritas são auditadas; os POST respeitam `Idempotency-Key`."""

from __future__ import annotations

from urllib.parse import urlsplit

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from analysis.models import Analysis
from api import filters, merge
from api import serializers as s
from api.mixins import AuditedModelViewSet, BaseViewSet, ReadOnlyViewSet, audit, to_json
from core import parameters
from core.models import AuditLog, Parameter
from crawl.models import Article, ArticleLink, Fetch, TechnicalFailure, Version
from duplicates.models import Cluster, ClusterMember
from entities.models import Entity, EntityAlias
from entities.normalize import normalize
from sources.models import DiscoveryRun, EntryPoint, Site
from topics.models import Edition, Topic

MERGE_RESPONSE = inline_serializer("MergeResult", {
    "dry_run": serializers.BooleanField(),
    "impact": serializers.DictField(),
    "audit_id": serializers.IntegerField(allow_null=True),
})


def _queued(result, queue: str) -> dict:
    return {"task_id": str(result.id), "queue": queue}


# Fontes ---------------------------------------------------------------------------------------------------------

class SiteViewSet(AuditedModelViewSet):
    queryset = Site.objects.all()
    serializer_class = s.SiteSerializer
    filterset_fields = ["active", "parser_module"]


class EntryPointViewSet(AuditedModelViewSet):
    queryset = EntryPoint.objects.select_related("site")
    serializer_class = s.EntryPointSerializer
    filterset_class = filters.EntryPointFilter

    @extend_schema(request=None, responses=s.TaskQueuedSerializer)
    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        """Põe a descoberta deste ponto de entrada na fila `discovery` já."""
        from sources.tasks import discover_entrypoint

        ep = self.get_object()
        res = discover_entrypoint.apply_async(args=[ep.pk], queue="discovery")
        data = _queued(res, "discovery")
        audit(request, "run", ep, extra=data)
        return Response(data, status=status.HTTP_202_ACCEPTED)


class DiscoveryRunViewSet(ReadOnlyViewSet):
    queryset = DiscoveryRun.objects.select_related("entrypoint__site")
    serializer_class = s.DiscoveryRunSerializer
    filterset_class = filters.DiscoveryRunFilter


# Notícias -------------------------------------------------------------------------------------------------------

class ArticleViewSet(ReadOnlyViewSet):
    filterset_class = filters.ArticleFilter

    def get_queryset(self):
        qs = Article.objects.select_related("site")
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                "urls", Prefetch("versions", queryset=Version.objects.only(
                    "id", "article_id", "number", "created_at", "change_ratio", "word_count", "fetch_id")))
        return qs

    def get_serializer_class(self):
        return s.ArticleDetailSerializer if self.action == "retrieve" else s.ArticleListSerializer

    @extend_schema(responses=s.VersionSummarySerializer(many=True))
    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        article = self.get_object()
        return Response(s.VersionSummarySerializer(article.versions.order_by("number"), many=True).data)

    @extend_schema(responses=s.VersionDetailSerializer,
                   parameters=[OpenApiParameter("number", OpenApiTypes.INT, OpenApiParameter.PATH)])
    @action(detail=True, methods=["get"], url_path=r"versions/(?P<number>[0-9]+)")
    def version(self, request, pk=None, number=None):
        """Versão n: conteúdo (Article.to_dict() do parser), diff face à anterior e texto."""
        article = self.get_object()
        v = get_object_or_404(Version, article=article, number=int(number))
        return Response(s.VersionDetailSerializer(v).data)

    @extend_schema(request=None, responses=s.TaskQueuedSerializer)
    @action(detail=True, methods=["post"])
    def refetch(self, request, pk=None):
        """Nova leitura manual (fila `crawl`)."""
        from crawl.tasks import fetch_article

        article = self.get_object()
        res = fetch_article.apply_async(args=[article.pk, "manual"], queue="crawl")
        data = _queued(res, "crawl")
        audit(request, "refetch", article, extra=data)
        return Response(data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(request=s.IngestSerializer, responses=inline_serializer("IngestResult", {
        "article": s.ArticleListSerializer(), "created": serializers.BooleanField(),
        "queued": serializers.BooleanField()}))
    @action(detail=False, methods=["post"])
    def ingest(self, request):
        """Regista um URL à mão e põe a leitura na fila (se a notícia for nova)."""
        from crawl import ingest
        from crawl.tasks import fetch_article
        from parsers.base import HomepageItem

        ser = s.IngestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        url = ser.validated_data["url"]
        site = Site.objects.filter(slug=ser.validated_data["site"]).first()
        if site is None:
            raise ValidationError({"site": "Site desconhecido."})
        host = (urlsplit(url).hostname or "").removeprefix("www.")
        site_host = (urlsplit(site.base_url).hostname or "").removeprefix("www.")
        if not host or not (host == site_host or host.endswith("." + site_host)):
            raise ValidationError({"url": f"O URL não é do site {site.slug} ({site_host})."})

        # Um ponto de entrada que não seja homepage (a homepage gravaria uma aparição falsa).
        ep = site.entrypoints.exclude(kind="homepage").order_by("pk").first()
        queued = False
        with transaction.atomic():
            if ep is not None:
                # register_item põe a leitura na fila (on_commit) quando a notícia é nova.
                article, created = ingest.register_item(site, ep, HomepageItem(url=url))
                queued = created and article.status == "discovered"
            else:
                article = ingest.find_article(site, None, [url])
                created = article is None
                if created:
                    article = Article.objects.create(site=site, canonical_url=url,
                                                     discovery_meta={"via": "manual"})
                    ingest.add_urls(article, [url], "discovered")
                    transaction.on_commit(lambda aid=article.pk: fetch_article.apply_async(
                        args=[aid, "new"], queue="crawl"))
                    queued = True
            audit(request, "ingest", article, after=s.ArticleListSerializer(article).data,
                  extra={"url": url, "created": created, "queued": queued})
        return Response({"article": s.ArticleListSerializer(article).data, "created": created, "queued": queued},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class VersionViewSet(ReadOnlyViewSet):
    queryset = Version.objects.select_related("article")
    filterset_fields = ["article", "number"]

    def get_serializer_class(self):
        return s.VersionDetailSerializer if self.action == "retrieve" else s.VersionSummarySerializer

    @extend_schema(request=None, responses=s.TaskQueuedSerializer)
    @action(detail=True, methods=["post"])
    def analyze(self, request, pk=None):
        """Põe a análise LLM desta versão na fila `analysis`."""
        from analysis.tasks import analyze_version

        v = self.get_object()
        res = analyze_version.apply_async(args=[v.pk], queue="analysis")
        data = _queued(res, "analysis")
        audit(request, "analyze", v, extra=data)
        return Response(data, status=status.HTTP_202_ACCEPTED)


class ArticleLinkViewSet(ReadOnlyViewSet):
    """Ligações do corpo das notícias (inline e embeds), com âmbito e plataforma."""
    queryset = ArticleLink.objects.select_related("article__site", "version", "target_site").order_by("-id")
    serializer_class = s.ArticleLinkSerializer
    filterset_class = filters.ArticleLinkFilter


class FetchViewSet(ReadOnlyViewSet):
    queryset = Fetch.objects.select_related("article__site")
    serializer_class = s.FetchSerializer
    filterset_class = filters.FetchFilter


class FailureViewSet(ReadOnlyViewSet):
    queryset = TechnicalFailure.objects.all()
    serializer_class = s.FailureSerializer
    filterset_class = filters.FailureFilter

    @extend_schema(request=None, responses=s.FailureSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Reabre a falha para o próximo sweep (next_retry_at = agora)."""
        f = self.get_object()
        before = s.FailureSerializer(f).data
        f.status, f.next_retry_at = "open", timezone.now()
        f.save(update_fields=["status", "next_retry_at", "last_at"])
        after = s.FailureSerializer(f).data
        audit(request, "retry", f, before=before, after=after)
        return Response(after)


# Parâmetros -----------------------------------------------------------------------------------------------------

class ParameterViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, BaseViewSet):
    """Parâmetros configuráveis. PATCH {value, reason}: o tipo tem de ser o do valor por omissão."""

    queryset = Parameter.objects.select_related("updated_by")
    serializer_class = s.ParameterSerializer
    lookup_field = "key"
    lookup_value_regex = r"[^/]+"
    http_method_names = ["get", "patch", "head", "options"]
    filterset_fields = {"key": ["exact", "startswith"]}

    def perform_update(self, serializer):
        reason = serializer.validated_data.get("reason", "")
        with transaction.atomic():
            before = to_json(s.ParameterSerializer(serializer.instance).data)
            instance = serializer.save(updated_by=self.request.user)   # Parameter.save invalida a cache
            audit(self.request, "update", instance, obj_id=instance.key, before=before,
                  after=s.ParameterSerializer(instance).data, extra={"reason": reason})


# Entidades ------------------------------------------------------------------------------------------------------

class EntityViewSet(AuditedModelViewSet):
    queryset = Entity.objects.prefetch_related("aliases")
    serializer_class = s.EntitySerializer
    filterset_class = filters.EntityFilter

    @extend_schema(responses=s.EntitySerializer(many=True))
    @action(detail=False, methods=["get"], url_path="review-queue")
    def review_queue(self, request):
        """Entidades por rever, as mais mencionadas primeiro."""
        qs = (self.filter_queryset(self.get_queryset()).filter(status="por_rever")
              .annotate(n_mentions=Count("mentions")).order_by("-n_mentions", "created_at"))
        page = self.paginate_queryset(qs)
        data = [{**s.EntitySerializer(e).data, "mentions": e.n_mentions} for e in page]
        return self.get_paginated_response(data)

    @extend_schema(request=s.AliasCreateSerializer, responses=s.EntityAliasSerializer)
    @action(detail=True, methods=["post"], url_path="aliases")
    def add_alias(self, request, pk=None):
        entity = self.get_object()
        ser = s.AliasCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        alias = ser.validated_data["alias"].strip()
        n = normalize(alias)
        if not n:
            raise ValidationError({"alias": "Alias vazio depois de normalizado."})
        if EntityAlias.objects.filter(entity=entity, normalized=n).exists():
            raise ValidationError({"alias": "Alias já existe nesta entidade."})
        a = EntityAlias.objects.create(entity=entity, alias=alias, normalized=n)
        data = s.EntityAliasSerializer(a).data
        others = list(EntityAlias.objects.filter(normalized=n).exclude(entity=entity)
                      .values_list("entity_id", flat=True))
        audit(request, "alias_add", entity, after=data, extra={"same_alias_in": others})
        return Response({**data, "same_alias_in": others}, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None},
                   parameters=[OpenApiParameter("alias_id", OpenApiTypes.INT, OpenApiParameter.PATH)])
    @action(detail=True, methods=["delete"], url_path=r"aliases/(?P<alias_id>[0-9]+)")
    def remove_alias(self, request, pk=None, alias_id=None):
        entity = self.get_object()
        a = get_object_or_404(EntityAlias, entity=entity, pk=int(alias_id))
        before = s.EntityAliasSerializer(a).data
        a.delete()
        audit(request, "alias_remove", entity, before=before)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=s.MergeSerializer, responses=MERGE_RESPONSE)
    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """Funde esta entidade noutra (`into`). Com dry_run (omissão) só devolve o impacto."""
        return _merge(request, self.get_object(), Entity, merge.entity_impact, merge.merge_entities,
                      s.EntitySerializer)


def _merge(request, src, model, impact_fn, merge_fn, serializer_cls):
    ser = s.MergeSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    dst = model.objects.filter(pk=ser.validated_data["into"]).first()
    if dst is None:
        raise ValidationError({"into": "Destino não existe."})
    dry = ser.validated_data["dry_run"]
    try:
        if dry:
            return Response({"dry_run": True, "impact": impact_fn(src, dst), "audit_id": None})
        before = {"source": serializer_cls(src).data, "target": serializer_cls(dst).data}
        impact = merge_fn(src, dst)
    except merge.MergeError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    src.refresh_from_db()
    dst.refresh_from_db()
    log = audit(request, "merge", src, before=before,
                after={"source": serializer_cls(src).data, "target": serializer_cls(dst).data},
                extra={"into": dst.pk, "impact": impact, "reason": ser.validated_data.get("reason", "")})
    return Response({"dry_run": False, "impact": impact, "audit_id": log.pk})


# Temas ----------------------------------------------------------------------------------------------------------

class TopicViewSet(AuditedModelViewSet):
    queryset = Topic.objects.all()
    filterset_class = filters.TopicFilter

    def get_queryset(self):
        qs = Topic.objects.all()
        return qs.prefetch_related("editions") if self.action == "retrieve" else qs

    def get_serializer_class(self):
        return s.TopicDetailSerializer if self.action == "retrieve" else s.TopicSerializer

    @extend_schema(responses=s.TopicSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="review-queue")
    def review_queue(self, request):
        """Temas por rever, os com mais notícias primeiro."""
        qs = (self.filter_queryset(Topic.objects.all()).filter(status="por_rever")
              .annotate(n_links=Count("article_links")).order_by("-n_links", "created_at"))
        page = self.paginate_queryset(qs)
        data = [{**s.TopicSerializer(t).data, "article_links": t.n_links} for t in page]
        return self.get_paginated_response(data)

    @extend_schema(responses=s.TopicSerializer(many=True),
                   parameters=[OpenApiParameter("limit", OpenApiTypes.INT)])
    @action(detail=False, methods=["get"], pagination_class=None, filter_backends=[])
    def hot(self, request):
        """Temas mais quentes (por temperatura), em cache durante cache.stats_s."""
        default = int(parameters.get("topics.hot_limit"))
        try:
            limit = max(1, min(int(request.query_params.get("limit", default)), 500))
        except ValueError:
            limit = default
        key = f"api:topics:hot:{limit}"
        data = cache.get(key)
        if data is None:
            qs = Topic.objects.filter(status="active", temperature__gt=0).order_by("-temperature")[:limit]
            data = to_json(s.TopicSerializer(qs, many=True).data)
            cache.set(key, data, int(parameters.get("cache.stats_s")))
        return Response(data)

    @extend_schema(methods=["get"], responses=s.EditionSerializer(many=True))
    @extend_schema(methods=["post"], request=s.EditionSerializer, responses=s.EditionSerializer)
    @action(detail=True, methods=["get", "post"])
    def editions(self, request, pk=None):
        topic = self.get_object()
        if request.method == "GET":
            return Response(s.EditionSerializer(topic.editions.order_by("starts_at", "label"), many=True).data)
        ser = s.EditionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if Edition.objects.filter(topic=topic, label=ser.validated_data["label"]).exists():
            raise ValidationError({"label": "Já existe uma edição com esta etiqueta."})
        e = ser.save(topic=topic)
        data = s.EditionSerializer(e).data
        audit(request, "create", e, after=data)
        return Response(data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.MergeSerializer, responses=MERGE_RESPONSE)
    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        """Funde este tema noutro (`into`): notícias, edições, filhos e temperatura. dry_run por omissão."""
        return _merge(request, self.get_object(), Topic, merge.topic_impact, merge.merge_topics,
                      s.TopicSerializer)


# Análises, duplicados, auditoria -----------------------------------------------------------------------------------

class AnalysisViewSet(ReadOnlyViewSet):
    filterset_class = filters.AnalysisFilter

    def get_queryset(self):
        qs = Analysis.objects.select_related("version")
        if self.action == "retrieve":
            qs = qs.prefetch_related("sources", "entities__entity", "topics__topic")
        return qs

    def get_serializer_class(self):
        return s.AnalysisDetailSerializer if self.action == "retrieve" else s.AnalysisListSerializer


class ClusterViewSet(ReadOnlyViewSet):
    queryset = Cluster.objects.prefetch_related(
        Prefetch("members", queryset=ClusterMember.objects.select_related("article__site")))
    serializer_class = s.ClusterSerializer
    filterset_class = filters.ClusterFilter


class AuditLogViewSet(ReadOnlyViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = s.AuditLogSerializer
    filterset_class = filters.AuditLogFilter
