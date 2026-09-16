from uuid import uuid4

from django.db import models


class Participant(models.Model):
    account_id = models.UUIDField(primary_key=True)
    allowed = models.BooleanField(default=False)
    changed_by_id = models.UUIDField()
    changed_at = models.DateTimeField()


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ("name", "id")


class Attribute(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="attributes")
    key = models.SlugField(max_length=64, allow_unicode=True)
    label = models.CharField(max_length=120)
    required = models.BooleanField(default=False)
    values = models.JSONField(default=list)

    class Meta:
        ordering = ("label", "id")
        constraints = [models.UniqueConstraint(fields=("category", "key"), name="catalog_attribute_key_unique")]


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner_id = models.UUIDField(null=True, db_index=True)
    seller_id = models.UUIDField(null=True, db_index=True)
    kind = models.CharField(max_length=16, choices=(("physical", "Физический"), ("digital", "Цифровой черновик"), ("common", "Общая карточка")))
    unit = models.CharField(max_length=2, choices=(("pc", "шт."), ("kg", "кг"), ("m", "м")))
    unit_locked = models.BooleanField(default=False)
    draft = models.JSONField(default=dict)
    draft_version = models.PositiveIntegerField(default=0)
    published = models.JSONField(null=True)
    published_version = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True)
    blocked = models.BooleanField(default=False)
    block_reason = models.CharField(max_length=1024, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(kind__in=("physical", "digital", "common")), name="catalog_product_kind_valid"),
            models.CheckConstraint(condition=models.Q(unit__in=("pc", "kg", "m")), name="catalog_product_unit_valid"),
            models.CheckConstraint(condition=(models.Q(kind="common", owner_id__isnull=True, seller_id__isnull=True) | (~models.Q(kind="common") & models.Q(owner_id__isnull=False, seller_id__isnull=False))), name="catalog_product_ownership_valid"),
            models.CheckConstraint(condition=(~models.Q(kind="digital") | models.Q(published__isnull=True)), name="catalog_no_digital_publication"),
        ]


class SavedProduct(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account_id = models.UUIDField(db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="saved_by")
    created_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("account_id", "product"), name="catalog_saved_product_unique")]


class Variant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    draft = models.JSONField(default=dict)
    published = models.JSONField(null=True)
    published_version = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=(("draft", "Черновик"), ("published", "Опубликован"), ("withdrawn", "Снят")), default="draft")
    withdrawal_version = models.PositiveIntegerField(default=0)
    restore_version = models.PositiveIntegerField(null=True)
    blocked = models.BooleanField(default=False)
    block_reason = models.CharField(max_length=1024, blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    price_version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("id",)
        constraints = [
            models.CheckConstraint(condition=(models.Q(price__isnull=True) | models.Q(price__gte=0)), name="catalog_variant_price_nonnegative"),
            models.CheckConstraint(condition=models.Q(state__in=("draft", "published", "withdrawn")), name="catalog_variant_state_valid"),
        ]


class StorageLocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    seller_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ("-is_default", "name", "id")
        constraints = [
            models.UniqueConstraint(fields=("seller_id", "name"), name="catalog_location_name_unique"),
            models.UniqueConstraint(fields=("seller_id",), condition=models.Q(is_default=True), name="catalog_one_default_location"),
        ]


class Stock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="stocks")
    location = models.ForeignKey(StorageLocation, on_delete=models.PROTECT, related_name="stocks")
    quantity = models.DecimalField(max_digits=19, decimal_places=3, null=True)
    version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("location__name", "id")
        constraints = [
            models.UniqueConstraint(fields=("variant", "location"), name="catalog_one_stock_per_location"),
            models.CheckConstraint(condition=(models.Q(quantity__isnull=True) | models.Q(quantity__gte=0)), name="catalog_stock_nonnegative"),
        ]


class Photo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="photos")
    attested_by_id = models.UUIDField()
    created_at = models.DateTimeField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()


class MatchRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    requester_id = models.UUIDField()
    source = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="match_requests")
    target = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="incoming_requests")
    source_version = models.PositiveIntegerField()
    target_version = models.PositiveIntegerField()
    source_fingerprint = models.CharField(max_length=64)
    target_fingerprint = models.CharField(max_length=64)
    reason = models.CharField(max_length=2000)
    state = models.CharField(max_length=12, choices=(("pending", "Ожидает"), ("approved", "Подтверждено"), ("rejected", "Отклонено"), ("stale", "Данные изменились")), default="pending")
    created_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True)
    reviewer_id = models.UUIDField(null=True)
    review_reason = models.CharField(max_length=1024, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [models.UniqueConstraint(fields=("source", "target"), condition=models.Q(state="pending"), name="catalog_one_pending_match")]


class OfferLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="offer_links")
    target = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="linked_offers")
    request = models.OneToOneField(MatchRequest, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    source_fingerprint = models.CharField(max_length=64)
    target_fingerprint = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("source",), condition=models.Q(active=True), name="catalog_one_active_offer_link")]


class Suggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    author_id = models.UUIDField()
    kind = models.CharField(max_length=16, choices=(("category", "Категория"), ("attribute", "Характеристика"), ("common", "Общая карточка")))
    target_id = models.UUIDField(null=True)
    text = models.CharField(max_length=2000)
    created_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True)
    reviewer_id = models.UUIDField(null=True)
    response = models.CharField(max_length=2000, blank=True)

    class Meta:
        ordering = ("created_at", "id")
