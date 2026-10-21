from datetime import date, datetime, time, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AuthorizationError,
    LicenseExpiredError,
    ValidationError,
)
from app.models import Account
from app.models import (
    BulkPriceRule,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    StockMovement,
    Store,
    Supplier,
    User,
)
from app.services.bulk_pricing_service import BulkPricingService
from app.services.financial_service import FinancialService


class PurchaseService:
    def __init__(self, session: Session, *, transaction_locked: bool = False):
        self.session = session
        self.financial = FinancialService(session)
        self.transaction_locked = transaction_locked

    def list_purchases(self, actor: User) -> list[dict]:
        self._require_owner(actor)
        rows = self.session.execute(
            select(PurchaseOrder, Supplier.name)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .order_by(PurchaseOrder.ordered_at.desc(), PurchaseOrder.id.desc())
        )
        purchases = []
        for purchase, supplier_name in rows:
            item = self.session.scalar(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.purchase_order_id == purchase.id)
                .order_by(PurchaseOrderItem.id)
                .limit(1)
            )
            product = (
                self.session.get(Product, item.product_id)
                if item is not None
                else None
            )
            purchases.append(
                {
                    "purchase": purchase,
                    "supplier_name": supplier_name,
                    "product_name": product.name if product else "-",
                    "qty": item.received_qty if item else 0,
                }
            )
        return purchases

    def active_suppliers(self, actor: User) -> list[Supplier]:
        self._require_owner(actor)
        return list(
            self.session.scalars(
                select(Supplier)
                .where(Supplier.deleted_at.is_(None))
                .order_by(Supplier.name)
            )
        )

    def active_products(self, actor: User) -> list[Product]:
        self._require_owner(actor)
        return list(
            self.session.scalars(
                select(Product)
                .where(
                    Product.deleted_at.is_(None),
                    Product.is_active.is_(True),
                )
                .order_by(Product.name)
            )
        )

    def get_product(self, actor: User, product_id: int) -> Product | None:
        self._require_owner(actor)
        return self.session.get(Product, product_id)

    def record_purchase(
        self,
        actor: User,
        *,
        supplier_id: int,
        product_id: int,
        quantity: int,
        unit_cost: int,
        payment_status: str,
        due_date: date | None,
        payment_account_id: int | None = None,
        dp_amount: int = 0,
    ) -> PurchaseOrder:
        self._require_owner(actor)
        if self.transaction_locked:
            raise LicenseExpiredError(
                "Masa lisensi berakhir; pencatatan pembelian baru terkunci."
            )
        self.financial.require_initialized()
        if quantity <= 0:
            raise ValidationError("Jumlah pembelian harus lebih dari 0.")
        if unit_cost < 0:
            raise ValidationError("Harga modal tidak boleh negatif.")
        if unit_cost == 0:
            raise ValidationError("Harga modal pembelian harus lebih dari Rp 0.")
        if payment_status not in {"PAID", "TEMPO", "DP"}:
            raise ValidationError(
                "Pilih status pembayaran Lunas, Tempo, atau DP (uang muka)."
            )
        if payment_status in {"TEMPO", "DP"} and due_date is None:
            raise ValidationError(
                "Tanggal jatuh tempo wajib untuk pembelian Tempo."
                if payment_status == "TEMPO"
                else "Tanggal jatuh tempo wajib untuk pembelian DP (uang muka)."
            )
        if payment_status == "PAID":
            due_date = None
        total = quantity * unit_cost
        if payment_status == "DP":
            if dp_amount <= 0:
                raise ValidationError("Jumlah DP (uang muka) harus lebih dari Rp 0.")
            if dp_amount >= total:
                raise ValidationError(
                    "Jumlah DP harus lebih kecil dari total pembelian."
                )
        elif dp_amount:
            raise ValidationError(
                "Jumlah DP hanya diisi pada status DP (uang muka)."
            )

        supplier = self.session.get(Supplier, supplier_id)
        if supplier is None or supplier.deleted_at is not None:
            raise ValidationError("Supplier tidak ditemukan atau tidak aktif.")
        product = self.session.get(Product, product_id)
        if (
            product is None
            or product.deleted_at is not None
            or not product.is_active
        ):
            raise ValidationError("Produk tidak ditemukan atau tidak aktif.")
        store = self.session.scalar(
            select(Store)
            .where(Store.deleted_at.is_(None))
            .order_by(Store.id)
            .limit(1)
        )
        if store is None:
            raise ValidationError("Data toko belum tersedia.")

        now = datetime.now(timezone.utc)
        payment_account = (
            self.session.get(Account, payment_account_id)
            if payment_account_id is not None
            else self.session.scalar(
                select(Account).where(Account.code == "1000")
            )
        )
        if payment_status in {"PAID", "DP"} and payment_account is None:
            raise ValidationError("Akun kas/bank untuk pembayaran tidak ditemukan.")
        order = PurchaseOrder(
            order_no=f"PO-{now:%Y%m%d}-{uuid4().hex[:8].upper()}",
            supplier_id=supplier.id,
            store_id=store.id,
            created_by=actor.id,
            status="RECEIVED",
            ordered_at=now,
            subtotal=total,
            payment_status="TEMPO",
            due_date=(
                datetime.combine(due_date, time.min).astimezone()
                if due_date is not None
                else now
            ),
            paid_amount=0,
        )
        stock_before = product.stock_qty
        previous_cost = product.purchase_price
        previous_selling = product.selling_price
        product.stock_qty += quantity
        product.purchase_price = unit_cost
        if (
            unit_cost > previous_cost
            and previous_cost > 0
            and previous_selling > 0
        ):
            updated_selling = (previous_selling * unit_cost) // previous_cost
            if updated_selling > previous_selling:
                product.selling_price = updated_selling
                self._follow_special_prices(
                    product, previous_selling, updated_selling
                )
        self.session.add(order)
        try:
            self.session.flush()
            self.session.add(
                PurchaseOrderItem(
                    purchase_order_id=order.id,
                    product_id=product.id,
                    ordered_qty=quantity,
                    received_qty=quantity,
                    unit_cost=unit_cost,
                )
            )
            self.session.add(
                StockMovement(
                    product_id=product.id,
                    movement_type="PURCHASE",
                    stock_before=stock_before,
                    qty=quantity,
                    stock_after=product.stock_qty,
                    reference_type="PURCHASE_ORDER",
                    reference_id=order.id,
                    note=f"Pembelian {order.order_no} dari {supplier.name}.",
                )
            )
            self.session.flush()
            self.financial.post_purchase(actor.id, order)
            if payment_status == "PAID":
                self.financial._record_document_payment(
                    actor=actor,
                    purchase=order,
                    amount=total,
                    payment_account_id=payment_account.id,
                    payment_method=(
                        "CASH" if payment_account.code == "1000" else "BANK"
                    ),
                    paid_at=now,
                )
                order.due_date = None
            elif payment_status == "DP":
                self.financial._record_document_payment(
                    actor=actor,
                    purchase=order,
                    amount=dp_amount,
                    payment_account_id=payment_account.id,
                    payment_method=(
                        "CASH" if payment_account.code == "1000" else "BANK"
                    ),
                    paid_at=now,
                )
                order.payment_status = "DP"
            self.session.commit()
            self.session.refresh(order)
        except Exception:
            self.session.rollback()
            raise
        return order

    def _follow_special_prices(
        self,
        product: Product,
        old_selling: int,
        new_selling: int,
    ) -> None:
        rules = self.session.scalars(
            select(BulkPriceRule).where(BulkPriceRule.product_id == product.id)
        )
        for rule in rules:
            if rule.pricing_mode == "PRICE":
                updated = (rule.special_price * new_selling) // old_selling
                if rule.special_price < updated < new_selling:
                    rule.special_price = updated
                    rule.discount_percent = (
                        BulkPricingService.discount_percent_for_price(
                            new_selling, updated
                        )
                    )
            else:
                rule.special_price = BulkPricingService.special_price(
                    new_selling, rule.discount_percent
                )

    def mark_paid(self, actor: User, purchase_id: int) -> PurchaseOrder:
        self._require_owner(actor)
        purchase = self.session.get(PurchaseOrder, purchase_id)
        if purchase is None:
            raise ValidationError("Pembelian tidak ditemukan.")
        if purchase.payment_status == "PAID":
            raise ValidationError("Pembelian ini sudah berstatus Lunas.")
        cash_account = self.session.scalar(
            select(Account).where(Account.code == "1000")
        )
        if cash_account is None:
            raise ValidationError("Akun Kas tidak ditemukan.")
        return self.financial.record_purchase_payment(
            actor,
            purchase_id,
            purchase.subtotal - purchase.paid_amount,
            cash_account.id,
            "CASH",
        )

    def record_payment(
        self,
        actor: User,
        purchase_id: int,
        amount: int,
        payment_account_id: int,
        payment_method: str,
    ) -> PurchaseOrder:
        if self.transaction_locked:
            raise LicenseExpiredError(
                "Masa lisensi berakhir; pembayaran pembelian baru terkunci."
            )
        return self.financial.record_purchase_payment(
            actor,
            purchase_id,
            amount,
            payment_account_id,
            payment_method,
        )

    @staticmethod
    def _require_owner(actor: User):
        if actor.role.name.upper() != "OWNER":
            raise AuthorizationError(
                "Hanya OWNER yang dapat mencatat pembelian supplier."
            )
