from django.views.decorators.http import require_safe

from open_marketplace.verification.public import get_demo_image_credits
from open_marketplace.web.errors import secure_render


@require_safe
def demo_image_credits(request):
    return secure_render(request, "demo_image_credits.html", {"credits": get_demo_image_credits()})
