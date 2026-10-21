import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Product, Supplier
from scripts.seed import SAMPLE_PRODUCTS, SAMPLE_SUPPLIERS, seed_data


@pytest.fixture
def seed_session():
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


def test_seed_adds_grocery_products_and_is_safe_to_rerun(seed_session: Session):
    assert seed_data(seed_session) == len(SAMPLE_PRODUCTS)
    seed_session.flush()
    products = list(seed_session.scalars(select(Product)))

    assert len(products) == len(SAMPLE_PRODUCTS)
    assert all(product.category_id and product.unit_id for product in products)
    assert all(product.stock_qty > 0 for product in products)
    assert all(product.selling_price >= product.purchase_price for product in products)
    assert all(product.supplier_id is not None for product in products)
    assert len({product.barcode for product in products}) == len(products)
    suppliers = list(seed_session.scalars(select(Supplier)))
    assert len(suppliers) == len(SAMPLE_SUPPLIERS)
    assert {product.supplier_id for product in products} <= {
        supplier.id for supplier in suppliers
    }

    first_product = products[0]
    first_product.selling_price = 123_456
    seed_session.flush()

    assert seed_data(seed_session) == 0
    assert first_product.selling_price == 123_456
    assert len(list(seed_session.scalars(select(Supplier)))) == len(SAMPLE_SUPPLIERS)
