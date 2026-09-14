from uuid import uuid4

_SENSITIVE_PATH_PREFIXES = (
    "/identity/verify-email/",
    "/identity/reset-password/",
    "/identity/recover-mandatory-totp/",
    "/access/staff-invitation/",
    "/staff/invitations/accept/",
)


class RequestIdMiddleware:
    header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid4()
        response = self.get_response(request)
        response[self.header_name] = str(request.request_id)
        if request.path.startswith(_SENSITIVE_PATH_PREFIXES):
            response["Cache-Control"] = "no-store"
            response["Referrer-Policy"] = "same-origin"
        return response
