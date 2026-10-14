"""Filtros da API (django-filter)."""

import django_filters as df
from django.db.models import Q

from analysis.models import Analysis
from core.models import AuditLog
from crawl.models import ArticleLink, Article, Fetch, TechnicalFailure
from duplicates.models import Cluster
from entities.models import Entity
from sources.models import DiscoveryRun, EntryPoint
from topics.models import Topic


class EntryPointFilter(df.FilterSet):
    site = df.CharFilter(field_name="site__slug")

    class Meta:
        model = EntryPoint
        fields = ["site", "kind", "active"]


class DiscoveryRunFilter(df.FilterSet):
    site = df.CharFilter(field_name="entrypoint__site__slug")
    since = df.IsoDateTimeFilter(field_name="started_at", lookup_expr="gte")

    class Meta:
        model = DiscoveryRun
        fields = ["entrypoint", "site", "ok", "since"]


class ArticleFilter(df.FilterSet):
    site = df.CharFilter(field_name="site__slug")
    topic = df.NumberFilter(field_name="versions__analyses__topics__topic", distinct=True)
    entity = df.NumberFilter(field_name="versions__analyses__entities__entity", distinct=True)
    q = df.CharFilter(field_name="title", lookup_expr="icontains")
    published_after = df.IsoDateTimeFilter(field_name="published_at", lookup_expr="gte")
    published_before = df.IsoDateTimeFilter(field_name="published_at", lookup_expr="lt")

    class Meta:
        model = Article
        fields = ["site", "status", "piece_type", "access", "topic", "entity", "q",
                  "published_after", "published_before"]


class FetchFilter(df.FilterSet):
    site = df.CharFilter(field_name="article__site__slug")
    since = df.IsoDateTimeFilter(field_name="requested_at", lookup_expr="gte")

    class Meta:
        model = Fetch
        fields = ["site", "article", "outcome", "quality_ok", "reason", "since"]


class ArticleLinkFilter(df.FilterSet):
    site = df.CharFilter(field_name="article__site__slug")
    target_site = df.CharFilter(field_name="target_site__slug")
    domain = df.CharFilter(field_name="domain", lookup_expr="iexact")

    class Meta:
        model = ArticleLink
        fields = ["article", "version", "kind", "scope", "platform", "is_document", "site", "target_site",
                  "target_article", "domain"]


class FailureFilter(df.FilterSet):
    site = df.CharFilter(method="filter_site")

    class Meta:
        model = TechnicalFailure
        fields = ["site", "status", "kind", "article", "entrypoint"]

    def filter_site(self, qs, name, value):
        return qs.filter(Q(article__site__slug=value) | Q(entrypoint__site__slug=value))


class EntityFilter(df.FilterSet):
    q = df.CharFilter(method="filter_q")

    class Meta:
        model = Entity
        fields = ["type", "status", "is_public", "parent", "q"]

    def filter_q(self, qs, name, value):
        from entities.normalize import normalize

        return qs.filter(Q(canonical_name__icontains=value)
                         | Q(aliases__normalized__contains=normalize(value))).distinct()


class TopicFilter(df.FilterSet):
    q = df.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Topic
        fields = ["status", "kind", "parent", "recurrence", "q"]


class AnalysisFilter(df.FilterSet):
    article = df.NumberFilter(field_name="version__article")

    class Meta:
        model = Analysis
        fields = ["status", "provider", "model", "prompt_version", "version", "article", "piece_type"]


class ClusterFilter(df.FilterSet):
    article = df.NumberFilter(field_name="members__article", distinct=True)

    class Meta:
        model = Cluster
        fields = ["origin", "original", "article"]


class AuditLogFilter(df.FilterSet):
    actor = df.CharFilter(field_name="actor__username")
    since = df.IsoDateTimeFilter(field_name="at", lookup_expr="gte")
    until = df.IsoDateTimeFilter(field_name="at", lookup_expr="lt")

    class Meta:
        model = AuditLog
        fields = ["actor", "action", "object_type", "object_id", "since", "until"]
