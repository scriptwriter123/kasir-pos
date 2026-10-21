from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InsufficientStockError,
    LicenseExpiredError,
    PaymentIncompleteError,
    ShiftNotOpenError,
)
from app.models import AuditLog, Payment, Product, Sale, SaleItem, Shift, StockMovement
from app.services.bulk_pricing_service import BulkPricingService
from app.services.financial_service import FinancialService


class SalesService:
    """Business transaction boundary for checkout."""

    def __init__(
        self,
        session: Session,
        *,
        transaction_locked: bool = False,
        lock_message: str | None = None,
    ):
        self.session = session
        self.bulk_pricing = BulkPricingService(session)
        self.financial = FinancialService(session)
        self.transaction_locked = transaction_locked
        self.lock_message = lock_message or (
            "Masa trial berakhir dan lisensi belum diperpanjang. "
            "Transaksi baru terkunci; data tetap dapat dibaca dan diekspor."
        )

    def checkout(self, sale: Sale, items: list[dict], payments: list[dict]):
        if self.transaction_locked:
            raise LicenseExpiredError(self.lock_message)
        if not self.financial.is_initialized():
            self.financial.ensure_auto_initialized(sale.cashier_id)
        else:
            self.financial.require_initialized()
        paid_amount = sum(int(payment["amount"]) for payment in payments)
        if paid_amount < sale.grand_total:
            raise PaymentIncompleteError("Pembayaran belum lunas.")

        try:
            shift = self.session.get(Shift, sale.shift_id)
            if (
                shift is None
                or shift.status != "OPEN"
                or shift.closed_at is not None
                or shift.cashier_id != sale.cashier_id
            ):
                raise ShiftNotOpenError("Buka shift sebelum menyelesaikan penjualan.")

            if not items:
                raise ValueError("Keranjang penjualan masih kosong.")

            self.session.add(sale)
            self.session.flush()

            calculated_total = 0
            sale_items = []
            for item in items:
                product = self.session.get(Product, int(item["product_id"]))
                if product is None:
                    raise ValueError("Produk tidak ditemukan.")

                qty = int(item["qty"])
                if qty <= 0:
                    raise ValueError("Qty harus lebih dari 0.")

                before = product.stock_qty
                if before < qty:
                    raise InsufficientStockError(
                        f"Stok {product.name} tidak mencukupi."
                    )

                product.stock_qty = before - qty
                discount = int(item.get("discount", 0))
                unit_price = self.bulk_pricing.unit_price(product, qty)
                line_total = (qty * unit_price) - discount
                if line_total < 0:
                    raise ValueError("Diskon item melebihi nilai barang.")
                calculated_total += line_total

                sale_item = SaleItem(
                    sale_id=sale.id,
                    product_id=product.id,
                    qty=qty,
                    unit_price=unit_price,
                    unit_cost=(
                        product.purchase_price
                        if product.purchase_price > 0
                        else None
                    ),
                    discount=discount,
                    line_total=line_total,
                )
                sale_items.append(sale_item)
                self.session.add(sale_item)

                self.session.add(StockMovement(
                    product_id=product.id,
                    movement_type="SALE",
                    stock_before=before,
                    qty=-qty,
                    stock_after=product.stock_qty,
                    reference_type="SALE",
                    reference_id=sale.id,
                ))

            if calculated_total != sale.grand_total:
                raise ValueError(
                    "Total transaksi tidak sesuai dengan harga produk saat ini."
                )
            if paid_amount < calculated_total:
                raise PaymentIncompleteError("Pembayaran belum lunas.")

            for payment in payments:
                self.session.add(Payment(
                    sale_id=sale.id,
                    method=payment["method"],
                    amount=int(payment["amount"]),
                    reference=payment.get("reference"),
                ))

            self.session.flush()
            self.financial.post_sale(
                sale.cashier_id,
                sale,
                payments,
                sale_items,
            )
            self.session.add(
                AuditLog(
                    user_id=sale.cashier_id,
                    action="SALE_COMPLETED",
                    entity_type="Sale",
                    entity_id=sale.id,
                    detail=f"Invoice {sale.invoice_no}; total {sale.grand_total}",
                )
            )
            self.session.flush()
            self.session.commit()
            self.session.refresh(sale)
            return sale
        except Exception:
            self.session.rollback()
            raise

    def daily_sales(self, on_date: date | None = None) -> list[Sale]:
        target_date = on_date or date.today()
        local_start = datetime.combine(target_date, time.min).astimezone(timezone.utc)
        local_end = datetime.combine(
            target_date + timedelta(days=1),
            time.min,
        ).astimezone(timezone.utc)
        statement = (
            select(Sale)
            .where(
                Sale.created_at >= local_start.replace(tzinfo=None),
                Sale.created_at < local_end.replace(tzinfo=None),
            )
            .order_by(Sale.created_at.desc(), Sale.id.desc())
        )
        return list(self.session.scalars(statement))

    def refund_sale(self, sale_id: int, reason: str = "") -> Sale:
        sale = self.session.get(Sale, sale_id)
        if sale is None:
            raise ValueError("Transaksi tidak ditemukan.")
        if sale.status == "REFUNDED":
            raise ValueError("Transaksi ini sudah pernah dibatalkan / direfund.")

        sale.status = "REFUNDED"
        items = list(self.session.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id)
        ))
        for item in items:
            product = self.session.get(Product, item.product_id)
            if product is not None:
                stock_before = product.stock_qty
                product.stock_qty += item.qty
                self.session.add(
                    StockMovement(
                        product_id=product.id,
                        movement_type="REFUND",
                        stock_before=stock_before,
                        qty=item.qty,
                        stock_after=product.stock_qty,
                        reference_type="SALE_REFUND",
                        reference_id=sale.id,
                        note=f"Retur/Refund invoice {sale.invoice_no}: {reason}".strip(),
                    )
                )

        self.session.add(
            AuditLog(
                user_id=sale.cashier_id,
                action="SALE_REFUNDED",
                entity_type="Sale",
                entity_id=sale.id,
                detail=f"Refund invoice {sale.invoice_no}; alasan: {reason}".strip(),
            )
        )
        try:
            self.session.commit()
            self.session.refresh(sale)
        except Exception:
            self.session.rollback()
            raise
        return sale

    @staticmethod
    def new_invoice_number() -> str:
        return f"POS-{date.today():%Y%m%d}-{uuid4().hex[:8].upper()}"
