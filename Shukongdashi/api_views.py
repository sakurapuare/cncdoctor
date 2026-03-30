from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .core.container import get_container
from .core.models import FaultQuery, FeedbackRecord
from .core.text import unique_preserve_order

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class BaseJsonView(View):
    def dispatch(self, request, *args, **kwargs):
        try:
            response = super().dispatch(request, *args, **kwargs)
        except Exception as exc:
            logger.exception("Unhandled API error on %s %s", request.method, request.path)
            response = self.respond(
                message="服务器内部错误",
                code=500,
                status=500,
                data={"detail": str(exc)} if self._debug_enabled() else None,
            )
        return self.with_cors(response)

    def payload(self, request) -> dict[str, Any]:
        cached = getattr(request, "_cached_api_payload", None)
        if cached is not None:
            return cached

        payload: dict[str, Any] = {}
        for source in (request.GET, request.POST):
            if not hasattr(source, "lists"):
                continue
            for key, values in source.lists():
                if not values:
                    continue
                payload[key] = values if len(values) > 1 else values[-1]

        content_type = request.META.get("CONTENT_TYPE", "")
        if "application/json" in content_type and request.body:
            try:
                json_payload = json.loads(request.body.decode("utf-8"))
                if isinstance(json_payload, dict):
                    payload.update(json_payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

        request._cached_api_payload = payload
        return payload

    def list_param(self, request, *names: str) -> list[str]:
        payload = self.payload(request)
        for name in names:
            if hasattr(request.GET, "getlist") and request.GET.getlist(name):
                return unique_preserve_order(request.GET.getlist(name))
            if hasattr(request.POST, "getlist") and request.POST.getlist(name):
                return unique_preserve_order(request.POST.getlist(name))
            raw = payload.get(name, "")
            if raw is None or raw == "":
                continue
            if isinstance(raw, list):
                return unique_preserve_order(str(item) for item in raw)
            return unique_preserve_order(raw.split("|"))
        return []

    def str_param(self, request, name: str, default: str = "") -> str:
        raw = self.payload(request).get(name, default)
        if isinstance(raw, list):
            raw = raw[-1] if raw else default
        return str(raw).strip()

    def respond(self, data: Any = None, message: str = "成功", code: int = 0, status: int = 200):
        return JsonResponse(
            {"code": code, "msg": message, "data": data},
            status=status,
            json_dumps_params={"ensure_ascii": False},
        )

    def http_method_not_allowed(self, request, *args, **kwargs):
        return self.respond(message="请求方法不被允许", code=405, status=405)

    def options(self, request, *args, **kwargs):
        return HttpResponse(status=204)

    def _debug_enabled(self) -> bool:
        try:
            from django.conf import settings
        except Exception:
            return False
        return bool(getattr(settings, "DEBUG", False))

    def with_cors(self, response):
        settings = getattr(get_container(), "settings", None)
        response["Access-Control-Allow-Origin"] = getattr(settings, "cors_allow_origin", "*")
        response["Access-Control-Allow-Methods"] = getattr(
            settings,
            "cors_allow_methods",
            "GET,POST,OPTIONS",
        )
        response["Access-Control-Allow-Headers"] = getattr(
            settings,
            "cors_allow_headers",
            "Content-Type,Authorization,X-Requested-With",
        )
        response["Access-Control-Max-Age"] = "86400"
        return response


class HealthView(BaseJsonView):
    def get(self, request):
        container = get_container()
        return self.respond(
            data={
                "service": "Shukongdashi",
                "features": ["qa", "pa", "save", "buquan", "wenda"],
                "graph_enabled": container.graph_repository.available(),
                "case_count": container.case_repository.case_count(),
                "classifier_backend": (
                    "cnn"
                    if getattr(container.classifier, "_cnn_backend", None) is not None
                    else "heuristic"
                ),
                "request_id": getattr(request, "request_id", ""),
            }
        )


class DocsView(BaseJsonView):
    def get(self, request):
        return self.respond(
            data={
                "service": "Shukongdashi API",
                "version": 2,
                "response_shape": {"code": 0, "msg": "成功", "data": {}},
                "endpoints": [
                    {
                        "path": "/health",
                        "methods": ["GET"],
                        "description": "系统健康状态与依赖后端状态",
                    },
                    {
                        "path": "/docs",
                        "methods": ["GET"],
                        "description": "接口说明",
                    },
                    {
                        "path": "/qa",
                        "methods": ["GET", "POST", "OPTIONS"],
                        "params": ["pinpai", "xinghao", "errorid", "question", "relationList"],
                        "description": "故障诊断",
                    },
                    {
                        "path": "/pa",
                        "methods": ["GET", "POST", "OPTIONS"],
                        "params": ["pinpai", "xinghao", "errorid", "question", "relationList"],
                        "description": "在线分析",
                    },
                    {
                        "path": "/save",
                        "methods": ["GET", "POST", "OPTIONS"],
                        "params": [
                            "pinpai",
                            "xinghao",
                            "errorid",
                            "question",
                            "selectedList",
                            "yuanyin",
                            "answer",
                        ],
                        "description": "反馈保存",
                    },
                    {
                        "path": "/buquan",
                        "methods": ["GET", "POST", "OPTIONS"],
                        "params": ["question_start"],
                        "description": "自动补全",
                    },
                    {
                        "path": "/wenda",
                        "methods": ["GET", "POST", "OPTIONS"],
                        "params": ["question"],
                        "description": "智能问答",
                    },
                ],
            }
        )


class DiagnosisView(BaseJsonView):
    def post(self, request):
        return self._handle(request)

    def get(self, request):
        return self._handle(request)

    def _handle(self, request):
        question = self.str_param(request, "question")
        if not question:
            return self.respond(message="缺少 question 参数", code=400, status=400)

        query = FaultQuery(
            brand=self.str_param(request, "pinpai"),
            model=self.str_param(request, "xinghao"),
            alarm_code=self.str_param(request, "errorid"),
            question=question,
            related_symptoms=self.list_param(request, "relationList", "selectedList"),
        )
        result = get_container().diagnosis_service.diagnose(query)
        if not result.candidates:
            return self.respond(
                message="没有找到类似的答案",
                code=404,
                status=404,
                data=result.to_dict(),
            )
        return self.respond(data=result.to_dict())


class OnlineAnalysisView(BaseJsonView):
    def post(self, request):
        return self._handle(request)

    def get(self, request):
        return self._handle(request)

    def _handle(self, request):
        question = self.str_param(request, "question")
        if not question:
            return self.respond(message="缺少 question 参数", code=400, status=400)

        query = FaultQuery(
            brand=self.str_param(request, "pinpai"),
            model=self.str_param(request, "xinghao"),
            alarm_code=self.str_param(request, "errorid"),
            question=question,
            related_symptoms=self.list_param(request, "relationList"),
        )
        result = get_container().online_analysis_service.analyze(query)
        return self.respond(data=result)


class FeedbackView(BaseJsonView):
    def dispatch(self, request, *args, **kwargs):
        if request.method not in {"GET", "POST"}:
            return self.respond(message="仅支持 GET/POST", code=405, status=405)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        answer = self.str_param(request, "answer")
        question = self.str_param(request, "question")
        if not answer or not question:
            return self.respond(message="缺少 question 或 answer 参数", code=400, status=400)

        feedback = FeedbackRecord(
            brand=self.str_param(request, "pinpai"),
            model=self.str_param(request, "xinghao"),
            alarm_code=self.str_param(request, "errorid"),
            question=question,
            selected_signals=self.list_param(request, "selectedList", "relationList"),
            cause=self.str_param(request, "yuanyin"),
            answer=answer,
        )
        result = get_container().feedback_service.save(feedback)
        return self.respond(data=result)


class CompletionView(BaseJsonView):
    def post(self, request):
        return self._handle(request)

    def get(self, request):
        return self._handle(request)

    def _handle(self, request):
        question_start = self.str_param(request, "question_start")
        if not question_start:
            return self.respond(message="缺少 question_start 参数", code=400, status=400)
        result = get_container().completion_service.complete(question_start)
        return self.respond(data=result.to_dict())


class QuestionView(BaseJsonView):
    def post(self, request):
        return self._handle(request)

    def get(self, request):
        return self._handle(request)

    def _handle(self, request):
        question = self.str_param(request, "question")
        if not question:
            return self.respond(message="缺少 question 参数", code=400, status=400)
        result = get_container().qa_service.answer(question)
        return self.respond(data=result.to_dict())
