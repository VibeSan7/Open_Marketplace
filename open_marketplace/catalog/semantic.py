from functools import lru_cache
from math import sqrt

from django.conf import settings

from open_marketplace.common.errors import ApplicationError

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MIN_SIMILARITY = 0.30


def prepare_model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(settings.CATALOG_MODEL_CACHE), threads=2, cuda=False, local_files_only=False)


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    try:
        return TextEmbedding(model_name=MODEL_NAME, cache_dir=str(settings.CATALOG_MODEL_CACHE), threads=2, cuda=False, local_files_only=True)
    except (ValueError, OSError, RuntimeError):
        raise ApplicationError("Смысловой поиск не подготовлен или его локальная модель недоступна. Владелец установки должен выполнить prepare_catalog_search.") from None


@lru_cache(maxsize=2048)
def _embedding(text):
    vector = next(iter(_model().embed([text])))
    values = tuple(float(value) for value in vector)
    norm = sqrt(sum(value * value for value in values))
    if norm == 0:
        raise ApplicationError("Модель поиска вернула некорректный результат. Поиск не выполнен.")
    return tuple(value / norm for value in values)


def similarities(query, documents):
    if not documents:
        return []
    query_vector = _embedding(query)
    result = []
    for text in documents:
        vector = _embedding(text)
        score = sum(left * right for left, right in zip(query_vector, vector, strict=True))
        result.append(max(-1.0, min(1.0, score)))
    return result
