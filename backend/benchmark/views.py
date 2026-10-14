"""API só de leitura do benchmark. Os runs correm pelos comandos `bench_*` (ver docs/features/analise.md)."""

from rest_framework import viewsets

from .models import BenchmarkRun, BenchResult, ModelConfig, SampleArticle
from .serializers import (
    BenchmarkRunSerializer, BenchResultSerializer, ModelConfigSerializer, SampleArticleSerializer,
)


class SampleArticleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SampleArticle.objects.all()
    serializer_class = SampleArticleSerializer


class ModelConfigViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ModelConfig.objects.all()
    serializer_class = ModelConfigSerializer


class BenchmarkRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BenchmarkRun.objects.prefetch_related("model_configs").select_related("prompt_version", "scoring_config")
    serializer_class = BenchmarkRunSerializer


class BenchResultViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BenchResultSerializer

    def get_queryset(self):
        qs = BenchResult.objects.select_related("article", "model_config", "score")
        params = self.request.query_params
        if params.get("run"):
            qs = qs.filter(run_id=params["run"])
        if params.get("model"):
            qs = qs.filter(model_config__name=params["model"])
        if params.get("baseline"):
            qs = qs.filter(is_baseline=True, baseline_label=params["baseline"])
        return qs
