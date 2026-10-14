"""Settings do Factos. Tudo o que muda entre ambientes vem de variáveis de ambiente (ver .env.example)."""

import os
from pathlib import Path

import environ
from kombu import Exchange, Queue

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    # Antes do admin: sobrepõe admin/base_site.html (link para o dashboard do crawl).
    "dashboard",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django.contrib.postgres",
    "rest_framework.authtoken",
    "django_filters",
    "django_celery_beat",
    "core",
    "sources",
    "crawl",
    "analysis",
    "entities",
    "topics",
    "duplicates",
    "benchmark",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Base de dados: Postgres + pgvector
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "CONN_MAX_AGE": env.int("POSTGRES_CONN_MAX_AGE", default=60),
        # BD de testes única por processo: várias sessões (agentes) podem correr pytest em paralelo.
        "TEST": {"NAME": env("POSTGRES_TEST_DB", default=f"test_factos_{os.getpid()}")},
    }
}

# Cache do front-office: instância Redis própria, com eviction (allkeys-lru).
# Nunca partilhar com o broker: a eviction apagaria tarefas da fila.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_CACHE_URL"),
        "TIMEOUT": env.int("CACHE_DEFAULT_TIMEOUT", default=300),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-pt"
TIME_ZONE = "Europe/Lisbon"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Manifest (nomes com hash) só com collectstatic feito: na imagem de produção (DJANGO_STATIC_MANIFEST=1).
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
                    if env.bool("DJANGO_STATIC_MANIFEST", default=False)
                    else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Atrás de um proxy (Traefik no Coolify, nginx): o SSL termina no proxy. Nunca SECURE_SSL_REDIRECT aqui.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env.bool("DJANGO_USE_X_FORWARDED_HOST", default=False)
SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=False)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# API
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Factos API",
    "VERSION": "0.1.0",
    # Vários modelos têm campos "status"/"kind" com escolhas diferentes: nomes explícitos no schema.
    "ENUM_NAME_OVERRIDES": {
        "ArticleStatusEnum": "crawl.models.Article.STATUS_CHOICES",
        "FailureStatusEnum": "crawl.models.TechnicalFailure.STATUS_CHOICES",
        "FailureKindEnum": "crawl.models.TechnicalFailure.KIND_CHOICES",
        "ArticleUrlKindEnum": "crawl.models.ArticleURL.KIND_CHOICES",
        "EntryPointKindEnum": "sources.models.EntryPoint.KIND_CHOICES",
        "AnalysisStatusEnum": "analysis.models.Analysis.STATUS_CHOICES",
        "ReviewStatusEnum": "entities.models.Entity.STATUS_CHOICES",
        "TopicKindEnum": "topics.models.Topic.KIND_CHOICES",
        "TopicStatusEnum": "topics.models.Topic.STATUS_CHOICES",
    },
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# Celery: Redis como broker, numa instância sem eviction (noeviction + AOF).
CELERY_BROKER_URL = env("REDIS_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=None)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# Filas por tipo de trabalho, cada uma com os seus workers (ver docs/features/arquitectura.md).
# As tarefas escolhem a fila com @shared_task(queue="...").
# Cada fila tem a sua exchange e routing key, para uma tarefa nunca ir parar a duas filas.
CELERY_QUEUE_NAMES = ("discovery", "crawl", "analysis", "enrichment", "revisits", "maintenance")
CELERY_TASK_QUEUES = [Queue(name, Exchange(name, type="direct"), routing_key=name) for name in CELERY_QUEUE_NAMES]
CELERY_TASK_DEFAULT_QUEUE = "maintenance"
CELERY_TASK_DEFAULT_EXCHANGE = "maintenance"
CELERY_TASK_DEFAULT_ROUTING_KEY = "maintenance"

# Tarefas idempotentes e com ack no fim: se um worker morrer, a tarefa volta à fila.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = env.int("CELERY_WORKER_PREFETCH_MULTIPLIER", default=1)
# Tem de ser maior que a tarefa mais longa (enriquecimento com pesquisa na internet), senão é re-entregue.
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": env.int("CELERY_VISIBILITY_TIMEOUT", default=3600),
}
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=1800)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=1500)

# Schedules na BD, editáveis pela API (django-celery-beat).
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# HTML completo de cada leitura (gzip), fora da BD.
RAW_HTML_ROOT = Path(env("RAW_HTML_ROOT", default=str(BASE_DIR / "data" / "raw")))

# LLM: as chaves ficam só no ambiente; fornecedor e modelo são parâmetros (core/parameters.py).
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", default="")
# Ollama Cloud (ollama.com), com OLLAMA_API_KEY em Authorization: Bearer. Vazio = https://ollama.com.
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="") or "https://ollama.com"
OLLAMA_API_KEY = env("OLLAMA_API_KEY", default="")

LOGIN_URL = "/admin/login/"

# Benchmark de LLMs (app benchmark): timeouts, contexto do Ollama e pasta dos artigos da PoC
LLM_REQUEST_TIMEOUT = env.int("LLM_REQUEST_TIMEOUT", default=600)
LLM_MAX_RETRIES = env.int("LLM_MAX_RETRIES", default=2)
OLLAMA_DEFAULT_NUM_CTX = env.int("OLLAMA_DEFAULT_NUM_CTX", default=16384)
ARTICLES_IMPORT_DIR = env("ARTICLES_IMPORT_DIR", default="/data/sites_out")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
