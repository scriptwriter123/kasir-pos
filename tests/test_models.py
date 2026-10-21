import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    Expense,
    Permission,
    PriceList,
    PriceListItem,
    Product,
    Promotion,
    PurchaseOrder,
    PurchaseOrderItem,
    Role,
    Sale,
    SaleItem,
    Shift,
    StockMovement,
    StockOpname,
    StockOpnameItem,
    Store,
    Supplier,
    role_permissions,
)


NEW_TABLES = {
    "permissions",
    "role_permissions",
    "price_lists",
    "price_list_items",
    "promotions",
    "purchase_orders",
    "purchase_order_items",
    "stock_opnames",
    "stock_opname_items",
    "expenses",
    "accounts",
    "financial_settings",
    "journal_entries",
    "journal_lines",
    "financial_payments",
    "payment_settings",
    "payment_wizard_states",
}


@pytest.fixture
def model_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_roadmap_tables_are_registered_in_metadata():
    assert NEW_TABLES <= set(Base.metadata.tables)
    # 35 tabel lama + inventaris_toko + login_history.
    assert len(Base.metadata.tables) == 37
    assert role_permissions.name == "role_permissions"


def test_promotion_rejects_percentage_over_one_hundred(model_session: Session):
    model_session.add(
        Promotion(
            code="BAD-PROMO",
            name="Invalid percentage",
            discount_type="PERCENT",
            discount_value=101,
        )
    )

    with pytest.raises(IntegrityError):
        model_session.commit()


def test_new_models_are_importable_from_app_models():
    assert all(
        model.__tablename__ in NEW_TABLES
        for model in (
            Expense,
            Permission,
            PriceList,
            PriceListItem,
            Product,
            Promotion,
            PurchaseOrder,
            PurchaseOrderItem,
            Role,
            Sale,
            SaleItem,
            Shift,
            StockMovement,
            StockOpname,
            StockOpnameItem,
            Store,
            Supplier,
        )
        if model.__tablename__ in NEW_TABLES
    )
