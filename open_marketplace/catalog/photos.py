from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

from open_marketplace.catalog.policy import identifier
from open_marketplace.common.errors import InputRejected

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000


def photo_path(photo_id):
    return Path(settings.CATALOG_MEDIA_ROOT) / f"{identifier(photo_id).hex}.png"


def normalize_photo(uploaded_file):
    raw = uploaded_file.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise InputRejected("Фото должно занимать не более 8 МиБ.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                raise InputRejected("Нужно статичное фото JPEG, PNG или WebP.")
            if source.width * source.height > MAX_PIXELS:
                raise InputRejected("Фото должно содержать не более 20 миллионов пикселей.")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            source = ImageOps.exif_transpose(source)
            source.load()
            mode = "RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB"
            converted = source.convert(mode)
            clean = Image.frombytes(mode, converted.size, converted.tobytes())
            out = BytesIO()
            clean.save(out, format="PNG")
            return out.getvalue(), clean.width, clean.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise InputRejected("Не удалось прочитать фото. Загрузите исправное изображение.") from None
