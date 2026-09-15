from django.core.management.base import BaseCommand, CommandError

from open_marketplace.catalog.semantic import MODEL_NAME, prepare_model


class Command(BaseCommand):
    help = "Однократно загрузить локальную многоязычную модель каталога (нужен интернет)."

    def handle(self, *args, **options):
        try:
            model = prepare_model()
            vector = next(iter(model.embed(["Проверка локального поиска"])))
        except Exception:
            raise CommandError("Не удалось подготовить модель. Проверьте доступ к Hugging Face и свободное место; существующие данные не изменены.") from None
        self.stdout.write(self.style.SUCCESS(f"Модель подготовлена: {MODEL_NAME}; размер вектора: {len(vector)}. Последующие поиски работают локально."))
