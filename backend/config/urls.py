from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", include("dashboard.urls")),
    path("api/health/", health, name="health"),
    path("api/benchmark/", include("benchmark.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    # Depois das rotas fixas: o router do api tem uma raiz em /api/.
    path("api/", include("api.urls")),
]
