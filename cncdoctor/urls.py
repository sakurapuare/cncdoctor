from django.urls import path

from .api_views import (
    CompletionView,
    DiagnosisView,
    DocsView,
    FeedbackView,
    HealthView,
    OnlineAnalysisView,
    QuestionView,
)

urlpatterns = [
    path("", HealthView.as_view(), name="health"),
    path("docs", DocsView.as_view(), name="docs"),
    path("docs/", DocsView.as_view(), name="docs-slash"),
    path("health", HealthView.as_view(), name="health-detail"),
    path("health/", HealthView.as_view(), name="health-detail-slash"),
    path("qa", DiagnosisView.as_view(), name="qa"),
    path("qa/", DiagnosisView.as_view(), name="qa-slash"),
    path("pa", OnlineAnalysisView.as_view(), name="pa"),
    path("pa/", OnlineAnalysisView.as_view(), name="pa-slash"),
    path("save", FeedbackView.as_view(), name="save"),
    path("save/", FeedbackView.as_view(), name="save-slash"),
    path("buquan", CompletionView.as_view(), name="buquan"),
    path("buquan/", CompletionView.as_view(), name="buquan-slash"),
    path("wenda", QuestionView.as_view(), name="wenda"),
    path("wenda/", QuestionView.as_view(), name="wenda-slash"),
]
