from django.http import HttpResponseNotAllowed

from open_marketplace.web.errors import secure_render, secure_response


def setup_guide(request):
    if request.method not in {"GET", "HEAD"}:
        return secure_response(HttpResponseNotAllowed(("GET", "HEAD")))
    return secure_render(request, "setup.html")
