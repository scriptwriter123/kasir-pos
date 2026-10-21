from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Role(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    whatsapp: Mapped[str | None] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    role: Mapped[Role] = relationship(back_populates="users")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Store(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slogan: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    whatsapp: Mapped[str | None] = mapped_column(String(30))
    logo_path: Mapped[str | None] = mapped_column(String(500))


class PaymentSettings(Base, TimestampMixin):
    __tablename__ = "payment_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    cash_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qris_dana_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qris_midtrans_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transfer_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PaymentWizardState(Base, TimestampMixin):
    __tablename__ = "payment_wizard_states"
    id: Mapped[int] = mapped_column(primary_key=True)
    method: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_started")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Category(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class Unit(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "units"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)


class Product(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    category: Mapped[Category | None] = relationship()
    unit: Mapped[Unit | None] = relationship()
    supplier: Mapped["Supplier | None"] = relationship()
    purchase_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selling_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LoginHistory(Base):
    """Riwayat login pengguna — sumber data absensi karyawan."""

    __tablename__ = "login_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    user: Mapped[User] = relationship()


class InventarisToko(Base, TimestampMixin, SoftDeleteMixin):
    """Inventaris toko: alat & peralatan yang tidak dijual."""

    __tablename__ = "inventaris_toko"
    id: Mapped[int] = mapped_column(primary_key=True)
    kode_inventaris: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    nama_barang: Mapped[str] = mapped_column(String(200), nullable=False)
    jumlah: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    satuan: Mapped[str | None] = mapped_column(String(50))
    tanggal_perolehan: Mapped[date | None] = mapped_column(Date)
    harga_perolehan: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    lokasi: Mapped[str | None] = mapped_column(String(100))
    kondisi: Mapped[str] = mapped_column(
        String(20), default="Baik", nullable=False
    )
    keterangan: Mapped[str | None] = mapped_column(Text)


class BulkPriceRule(Base, TimestampMixin):
    __tablename__ = "bulk_price_rules"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "quantity_threshold",
            name="uq_bulk_price_rules_product_threshold",
        ),
        CheckConstraint(
            "quantity_threshold >= 1",
            name="ck_bulk_price_rules_quantity_threshold_positive",
        ),
        CheckConstraint(
            "discount_percent > 0 AND discount_percent <= 100",
            name="ck_bulk_price_rules_discount_percent_range",
        ),
        CheckConstraint(
            "special_price >= 0",
            name="ck_bulk_price_rules_special_price_nonnegative",
        ),
        CheckConstraint(
            "pricing_mode IN ('PRICE', 'PERCENT')",
            name="ck_bulk_price_rules_pricing_mode",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    special_price: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    pricing_mode: Mapped[str] = mapped_column(
        String(10),
        default="PERCENT",
        nullable=False,
    )
    product: Mapped[Product] = relationship()


class Shift(Base, TimestampMixin):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opening_cash: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closing_cash: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)


class Customer(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))


class Supplier(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)


class Sale(Base, TimestampMixin):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    subtotal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tax: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grand_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PAID", nullable=False)
    cashier: Mapped[User] = relationship()


class CashierDailyReport(Base, TimestampMixin):
    __tablename__ = "cashier_daily_reports"
    __table_args__ = (
        UniqueConstraint("cashier_id", "report_date"),
        CheckConstraint(
            "sales_count >= 0 AND sales_total >= 0",
            name="ck_cashier_daily_reports_totals_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sales_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sales_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cashier: Mapped[User] = relationship()


class SaleItem(Base, TimestampMixin):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[int | None] = mapped_column(Integer)
    discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))


class StockMovement(Base, TimestampMixin):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


class PaymentMethod(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class PriceList(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "price_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PriceListItem(Base, TimestampMixin):
    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint("price_list_id", "product_id"),
        CheckConstraint("price >= 0", name="ck_price_list_items_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    price_list_id: Mapped[int] = mapped_column(
        ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)


class Promotion(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint(
            "discount_type IN ('AMOUNT', 'PERCENT')",
            name="ck_promotions_discount_type",
        ),
        CheckConstraint(
            "discount_value > 0",
            name="ck_promotions_discount_value_positive",
        ),
        CheckConstraint(
            "discount_type != 'PERCENT' OR discount_value <= 100",
            name="ck_promotions_percent_at_most_100",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at",
            name="ck_promotions_date_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    discount_type: Mapped[str] = mapped_column(String(10), nullable=False)
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_purchase_orders_subtotal_nonnegative"),
        CheckConstraint(
            "payment_status IN ('PAID', 'TEMPO', 'DP')",
            name="ck_purchase_orders_payment_status",
        ),
        CheckConstraint(
            "paid_amount >= 0 AND paid_amount <= subtotal",
            name="ck_purchase_orders_paid_amount",
        ),
        CheckConstraint(
            "(payment_status = 'PAID' AND paid_amount = subtotal) OR "
            "(payment_status = 'TEMPO' AND due_date IS NOT NULL) OR "
            "(payment_status = 'DP' AND paid_amount > 0 "
            "AND paid_amount < subtotal AND due_date IS NOT NULL)",
            name="ck_purchase_orders_payment_terms",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subtotal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(20), default="PAID", nullable=False
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class PurchaseOrderItem(Base, TimestampMixin):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("ordered_qty > 0", name="ck_purchase_order_items_qty_positive"),
        CheckConstraint("received_qty >= 0", name="ck_purchase_order_items_received_nonnegative"),
        CheckConstraint("unit_cost >= 0", name="ck_purchase_order_items_unit_cost_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    ordered_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    received_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost: Mapped[int] = mapped_column(Integer, nullable=False)


class StockOpname(Base, TimestampMixin):
    __tablename__ = "stock_opnames"
    id: Mapped[int] = mapped_column(primary_key=True)
    opname_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False)
    counted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class StockOpnameItem(Base, TimestampMixin):
    __tablename__ = "stock_opname_items"
    __table_args__ = (
        UniqueConstraint("stock_opname_id", "product_id"),
        CheckConstraint("system_qty >= 0", name="ck_stock_opname_items_system_nonnegative"),
        CheckConstraint("counted_qty >= 0", name="ck_stock_opname_items_counted_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_opname_id: Mapped[int] = mapped_column(
        ForeignKey("stock_opnames.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    system_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    counted_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        CheckConstraint(
            "payment_status IN ('CASH', 'HUTANG', 'DP')",
            name="ck_expenses_payment_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="CASH", server_default="CASH"
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    payee: Mapped[str | None] = mapped_column(String(150))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    incurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint(
            "account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')",
            name="ck_accounts_account_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class FinancialSettings(Base, TimestampMixin):
    __tablename__ = "financial_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    initialized_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JournalEntry(Base, TimestampMixin):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_journal_entries_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    memo: Mapped[str] = mapped_column(String(250), nullable=False)
    posted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
    )


class JournalLine(Base, TimestampMixin):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_journal_lines_one_sided_amount",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_entry_id: Mapped[int] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    debit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(250))
    account: Mapped[Account] = relationship()
    entry: Mapped[JournalEntry] = relationship(back_populates="lines")


class FinancialPayment(Base, TimestampMixin):
    __tablename__ = "financial_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_financial_payments_amount_positive"),
        CheckConstraint(
            "(purchase_order_id IS NOT NULL AND expense_id IS NULL) OR "
            "(purchase_order_id IS NULL AND expense_id IS NOT NULL)",
            name="ck_financial_payments_single_document",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id"),
        index=True,
    )
    expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id"),
        index=True,
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    account: Mapped[Account] = relationship()


class CashTransaction(Base, TimestampMixin):
    __tablename__ = "cash_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
