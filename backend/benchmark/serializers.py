from rest_framework import serializers

from .models import BenchmarkRun, BenchmarkScore, BenchResult, ModelConfig, SampleArticle


class SampleArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SampleArticle
        fields = ["id", "site", "site_article_id", "url", "title", "piece_type_site", "word_count", "published_at"]


class ModelConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelConfig
        fields = ["id", "name", "provider", "model_id", "base_url", "params", "price_input_per_mtok",
                  "price_output_per_mtok", "concurrency", "active", "notes"]


class BenchmarkRunSerializer(serializers.ModelSerializer):
    model_configs = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    prompt_version = serializers.StringRelatedField()
    scoring_config = serializers.StringRelatedField()

    class Meta:
        model = BenchmarkRun
        fields = ["id", "baseline_label", "prompt_version", "scoring_config", "model_configs", "repeat", "status",
                  "summary", "notes", "started_at", "finished_at"]


class BenchmarkScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = BenchmarkScore
        fields = ["metrics", "total", "details"]


class BenchResultSerializer(serializers.ModelSerializer):
    article = serializers.StringRelatedField()
    model_config = serializers.SlugRelatedField(slug_field="name", read_only=True)
    score = BenchmarkScoreSerializer(read_only=True)

    class Meta:
        model = BenchResult
        fields = ["id", "article", "model_config", "run", "attempt", "is_baseline", "baseline_label", "output",
                  "valid_schema", "error", "latency_ms", "tokens_in", "tokens_out", "cost_usd", "provider_meta",
                  "score", "created_at"]
