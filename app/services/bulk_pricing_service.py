from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import BulkPriceRule, Product, User

MAX_BULK_PRICE_TIERS = 3


class BulkPricingService:
    def __init__(self, session: Session):
        self.session = session

    def rules_for_product(self, product_id: int) -> list[BulkPriceRule]:
        return list(
            self.session.scalars(
                select(BulkPriceRule)
                .where(BulkPriceRule.product_id == product_id)
                .order_by(BulkPriceRule.quantity_threshold)
            )
        )

    def rule_for_product(self, product_id: int) -> BulkPriceRule | None:
        rules = self.rules_for_product(product_id)
        return rules[0] if rules else None

    def rules(self) -> list[BulkPriceRule]:
        return list(
            self.session.scalars(
                select(BulkPriceRule)
                .join(Product)
                .where(Product.deleted_at.is_(None))
                .order_by(Product.name, Product.sku)
            )
        )

    def save_rules(
        self,
        actor: User,
        product_id: int,
        tiers: list[dict],
    ) -> list[BulkPriceRule]:
        self._require_owner(actor)
        product = self.session.get(Product, product_id)
        if product is None or product.deleted_at is not None:
            raise ValidationError("Produk yang dipilih tidak ditemukan.")
        if not tiers:
            raise ValidationError(
                "Aktifkan minimal satu tingkat harga spesial partai."
            )
        if len(tiers) > MAX_BULK_PRICE_TIERS:
            raise ValidationError(
                f"Maksimal {MAX_BULK_PRICE_TIERS} tingkat harga spesial partai."
            )
        thresholds = [int(tier["quantity_threshold"]) for tier in tiers]
        if len(set(thresholds)) != len(thresholds):
            raise ValidationError(
                "Qty ambang tiap tingkat harus berbeda (contoh 2, 3, dan 5)."
            )
        validated = [
            self._validated_tier(product, tier) for tier in tiers
        ]

        existing = {
            rule.quantity_threshold: rule
            for rule in self.rules_for_product(product_id)
        }
        saved: list[BulkPriceRule] = []
        for threshold, percent, special_price, pricing_mode in validated:
            rule = existing.pop(threshold, None)
            if rule is None:
                rule = BulkPriceRule(
                    product_id=product_id,
                    quantity_threshold=threshold,
                )
                self.session.add(rule)
            rule.discount_percent = percent
            rule.special_price = special_price
            rule.pricing_mode = pricing_mode
            saved.append(rule)
        for stale in existing.values():
            self.session.delete(stale)
        try:
            self.session.commit()
            for rule in saved:
                self.session.refresh(rule)
        except Exception:
            self.session.rollback()
            raise
        return saved

    def save_rule(
        self,
        actor: User,
        product_id: int,
        quantity_threshold: int,
        discount_percent: Decimal,
        special_price: int,
        pricing_mode: str,
    ) -> BulkPriceRule:
        rules = self.save_rules(
            actor,
            product_id,
            [
                {
                    "quantity_threshold": quantity_threshold,
                    "discount_percent": discount_percent,
                    "special_price": special_price,
                    "pricing_mode": pricing_mode,
                }
            ],
        )
        return rules[0]

    def _validated_tier(
        self,
        product: Product,
        tier: dict,
    ) -> tuple[int, Decimal, int, str]:
        quantity_threshold = int(tier["quantity_threshold"])
        special_price = int(tier["special_price"])
        pricing_mode = tier["pricing_mode"]
        if quantity_threshold < 1:
            raise ValidationError("Batas qty harus minimal 1.")
        if product.selling_price <= 0:
            raise ValidationError(
                "Harga jual produk harus lebih dari Rp 0 untuk mengatur harga spesial."
            )
        if pricing_mode not in {"PRICE", "PERCENT"}:
            raise ValidationError("Pilih mekanisme harga spesial yang valid.")
        if pricing_mode == "PRICE":
            if special_price < 0 or special_price >= product.selling_price:
                raise ValidationError(
                    "Harga spesial harus minimal Rp 0 dan lebih rendah dari harga satuan."
                )
            percent = self.discount_percent_for_price(
                product.selling_price,
                special_price,
            )
            if percent <= 0:
                raise ValidationError(
                    "Selisih harga terlalu kecil untuk ditampilkan sebagai persentase."
                )
        else:
            percent = Decimal(tier["discount_percent"])
            if percent <= 0 or percent > 100:
                raise ValidationError(
                    "Potongan harga harus lebih dari 0% hingga 100%."
                )
            special_price = self.special_price(product.selling_price, percent)
        return quantity_threshold, percent, special_price, pricing_mode

    def delete_rule(self, actor: User, product_id: int) -> bool:
        self._require_owner(actor)
        rules = self.rules_for_product(product_id)
        if not rules:
            return False
        try:
            for rule in rules:
                self.session.delete(rule)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return True

    def unit_price(self, product: Product, quantity: int) -> int:
        best: BulkPriceRule | None = None
        for rule in self.rules_for_product(product.id):
            if quantity < rule.quantity_threshold:
                break
            best = rule
        if best is None:
            return product.selling_price
        return self.effective_special_price(product, best)

    @staticmethod
    def special_price(
        regular_price: int,
        discount_percent: Decimal,
    ) -> int:
        discounted = Decimal(regular_price) * (
            Decimal("1") - Decimal(discount_percent) / Decimal("100")
        )
        return int(discounted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def discount_percent_for_price(regular_price: int, special_price: int) -> Decimal:
        return (
            (Decimal(regular_price - special_price) * Decimal("100"))
            / Decimal(regular_price)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def effective_special_price(
        self,
        product: Product,
        rule: BulkPriceRule,
    ) -> int:
        if rule.pricing_mode == "PRICE":
            return rule.special_price
        return self.special_price(product.selling_price, rule.discount_percent)

    @staticmethod
    def _require_owner(actor: User):
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError("Hanya OWNER yang dapat mengatur harga spesial.")
