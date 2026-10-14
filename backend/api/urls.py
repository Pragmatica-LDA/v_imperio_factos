from django.urls import path
from rest_framework.routers import DefaultRouter

from api import front, stats, views

router = DefaultRouter()
router.register("sites", views.SiteViewSet, basename="site")
router.register("entrypoints", views.EntryPointViewSet, basename="entrypoint")
router.register("discovery-runs", views.DiscoveryRunViewSet, basename="discovery-run")
router.register("articles", views.ArticleViewSet, basename="article")
router.register("versions", views.VersionViewSet, basename="version")
router.register("fetches", views.FetchViewSet, basename="fetch")
router.register("links", views.ArticleLinkViewSet, basename="link")
router.register("failures", views.FailureViewSet, basename="failure")
router.register("parameters", views.ParameterViewSet, basename="parameter")
router.register("entities", views.EntityViewSet, basename="entity")
router.register("topics", views.TopicViewSet, basename="topic")
router.register("analyses", views.AnalysisViewSet, basename="analysis")
router.register("duplicates/clusters", views.ClusterViewSet, basename="cluster")
router.register("audit", views.AuditLogViewSet, basename="audit")

urlpatterns = [
    path("stats/", stats.StatsView.as_view(), name="stats"),
    path("stats/crawl-health/", stats.CrawlHealthView.as_view(), name="crawl-health"),
    # Login do front-office: utilizador + password → token DRF.
    path("auth/token/", front.LoginView.as_view(), name="auth-token"),
    path("front/overview/", front.OverviewView.as_view(), name="front-overview"),
    path("front/articles/", front.ArticlesView.as_view(), name="front-articles"),
    path("front/articles/<int:pk>/", front.ArticleDetailView.as_view(), name="front-article"),
    path("front/entities/<int:pk>/", front.EntityDetailView.as_view(), name="front-entity"),
    path("front/topics/<int:pk>/", front.TopicDetailView.as_view(), name="front-topic"),
    path("front/search/", front.SearchView.as_view(), name="front-search"),
    *router.urls,
]
