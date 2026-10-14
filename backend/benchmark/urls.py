from rest_framework.routers import DefaultRouter

from .views import BenchmarkRunViewSet, BenchResultViewSet, ModelConfigViewSet, SampleArticleViewSet

router = DefaultRouter()
router.register("articles", SampleArticleViewSet, basename="bench-article")
router.register("models", ModelConfigViewSet, basename="bench-model")
router.register("runs", BenchmarkRunViewSet, basename="bench-run")
router.register("results", BenchResultViewSet, basename="bench-result")

urlpatterns = router.urls
