from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("crawl/", views.crawl, name="crawl"),
    path("analysis/", views.analysis_queue, name="analysis"),
    path("articles/<int:pk>/", views.article, name="article"),
    path("articles/<int:pk>/analyze/", views.analyze_now, name="analyze_now"),
]
