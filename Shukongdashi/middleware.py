import uuid

from Shukongdashi.core.container import get_container


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get("HTTP_X_REQUEST_ID", str(uuid.uuid4()))
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response


class ApiCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        settings = get_container().settings
        response["Access-Control-Allow-Origin"] = settings.cors_allow_origin
        response["Access-Control-Allow-Methods"] = settings.cors_allow_methods
        response["Access-Control-Allow-Headers"] = settings.cors_allow_headers
        response["Access-Control-Max-Age"] = "86400"
        return response
