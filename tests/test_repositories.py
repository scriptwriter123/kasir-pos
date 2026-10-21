from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    Product,
    Role,
    Sale,
    SaleItem,
    Shift,
    StockMovement,
    Store,
    User,
)
from app.repositories.sale_repository import SaleRepository
from app.repositories.shift_repository import ShiftRepository
from app.repositories.stock_movement_repository import StockMovementRepository


@pytest.fixture
def repository_session():
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


def make_cashier(session: Session) -> User:
    role = Role(name="CASHIER")
    session.add(role)
    session.flush()
    user = User(
        username="cashier",
        full_name="Test Cashier",
        password_hash="not-used-in-this-test",
        role_id=role.id,
    )
    session.add(user)
    session.flush()
    return user


def test_sale_repository_finds_invoice_and_paginates_by_cashier(
    repository_session: Session,
):
    cashier = make_cashier(repository_session)
    store = make_store(repository_session)
    shift = make_shift(repository_session, cashier, store.id)
    first = Sale(
        invoice_no="INV-001",
        store_id=store.id,
        shift_id=shift.id,
        cashier_id=cashier.id,
        subtotal=100,
        discount=0,
        tax=0,
        grand_total=100,
    )
    repository_session.add(first)
    repository_session.flush()
    product = Product(sku="SKU-001", name="Test Product")
    repository_session.add(product)
    repository_session.flush()
    item = SaleItem(
        sale_id=first.id,
        product_id=product.id,
        qty=1,
        unit_price=100,
        discount=0,
        line_total=100,
    )
    second = Sale(
        invoice_no="INV-002",
        store_id=first.store_id,
        shift_id=first.shift_id,
        cashier_id=cashier.id,
        subtotal=200,
        discount=0,
        tax=0,
        grand_total=200,
    )
    repository_session.add_all([second, item])
    repository_session.flush()
    repository = SaleRepository(repository_session)

    assert repository.get_by_invoice_no("INV-001") is first
    assert repository.get_by_invoice_no("missing") is None
    assert repository.list_for_cashier(cashier.id, limit=1) == [second]
    assert repository.list_for_cashier(cashier.id, offset=1) == [first]
    assert repository.list_items(first.id) == [item]


def test_stock_movement_repository_filters_and_paginates_by_product(
    repository_session: Session,
):
    product = Product(sku="SKU-001", name="Test Product")
    other_product = Product(sku="SKU-002", name="Other Product")
    repository_session.add_all([product, other_product])
    repository_session.flush()
    older = make_movement(repository_session, product, "PURCHASE")
    newer = make_movement(repository_session, product, "SALE")
    make_movement(repository_session, other_product, "ADJUSTMENT")
    repository_session.flush()
    repository = StockMovementRepository(repository_session)

    assert repository.list_for_product(product.id, limit=1) == [newer]
    assert repository.list_for_product(product.id, offset=1) == [older]


def test_shift_repository_returns_only_open_shift_for_cashier(
    repository_session: Session,
):
    cashier = make_cashier(repository_session)
    store = make_store(repository_session)
    open_shift = Shift(
        store_id=store.id,
        cashier_id=cashier.id,
        opened_at=datetime.now(timezone.utc),
        opening_cash=0,
        status="OPEN",
    )
    closed_shift = Shift(
        store_id=store.id,
        cashier_id=cashier.id,
        opened_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
        opening_cash=0,
        status="CLOSED",
    )
    repository_session.add_all([open_shift, closed_shift])
    repository_session.flush()

    assert ShiftRepository(repository_session).get_open_for_cashier(cashier.id) is open_shift
    assert ShiftRepository(repository_session).get_open_for_cashier(-1) is None


def make_store(session: Session) -> Store:
    store = Store(code="MAIN", name="Test Store")
    session.add(store)
    session.flush()
    return store


def make_shift(session: Session, cashier: User, store_id: int) -> Shift:
    shift = Shift(
        store_id=store_id,
        cashier_id=cashier.id,
        opened_at=datetime.now(timezone.utc),
        opening_cash=0,
        status="OPEN",
    )
    session.add(shift)
    session.flush()
    return shift


def make_movement(session: Session, product: Product, movement_type: str):
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        stock_before=10,
        qty=1,
        stock_after=11,
    )
    session.add(movement)
    return movement
