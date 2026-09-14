from django.shortcuts import render


EXPECTED_ERROR_MESSAGE = "Unable to complete this request."
NEUTRAL_EMAIL_MESSAGE = "If the details are eligible, check your email."


def secure_response(response):
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


def secure_render(request, template_name, context=None, *, status=200):
    return secure_response(
        render(request, template_name, context or {}, status=status)
    )


def handler500(request):
    request_id = getattr(request, "request_id", None)
    return secure_render(
        request,
        "errors/500.html",
        {"request_id": request_id},
        status=500,
    )
