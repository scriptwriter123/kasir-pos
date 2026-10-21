import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import faulthandler

faulthandler.dump_traceback_later(25, exit=True)

from decimal import Decimal

from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Category, Role, Unit, User
from app.services.bulk_pricing_service import BulkPricingService
from app.services.master_data_service import MasterDataService
from app.ui.views.master_data_view import BulkPriceDialog, MasterDataView


def main():
    app = QApplication.instance() or QApplication([])
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner_role = Role(name="OWNER")
        category = Category(name="Minuman")
        unit = Unit(name="Piece", symbol="pcs")
        session.add_all([owner_role, category, unit])
        session.flush()
        owner = User(
            username="owner",
            full_name="Test Owner",
            password_hash="unused",
            role=owner_role,
        )
        session.add(owner)
        session.flush()
        product = MasterDataService(session).save_product(
            owner,
            product_id=None,
            sku="BULK-001",
            barcode="",
            name="Produk Partai",
            category_id=category.id,
            unit_id=unit.id,
            purchase_price=1_000,
            selling_price=2_000,
            stock_qty=10,
            min_stock=0,
            is_active=True,
        )
        print("STEP create view", flush=True)
        view = MasterDataView(owner, session)
        print("STEP create dialog", flush=True)
        dialog = BulkPriceDialog(
            BulkPricingService(session), owner, [product], view
        )
        print("STEP dialog ok", flush=True)
        print(
            "tier0 thr:",
            dialog.tier_rows[0].threshold_input.value(),
            flush=True,
        )
        dialog.tier_rows[0].threshold_input.setValue(5)
        print("STEP set thr 5", flush=True)
        dialog.tier_rows[0].discount_input.setValue(12.5)
        print(
            "STEP set disc 12.5, price:",
            dialog.tier_rows[0].price_input.value(),
            flush=True,
        )
        from PySide6.QtWidgets import QMessageBox

        def _fake(*_args, **_kwargs):
            print("MSG:", _args[1] if len(_args) > 1 else "", "|", _args[2] if len(_args) > 2 else "", flush=True)
            return QMessageBox.StandardButton.Ok

        QMessageBox.information = _fake
        QMessageBox.warning = _fake
        print("STEP save_rule 1", flush=True)
        tiers = dialog._active_tiers()
        print("tiers:", tiers, flush=True)
        try:
            BulkPricingService(session).save_rules(owner, product.id, tiers)
            print("save_rules langsung OK", flush=True)
        except Exception as exc:
            print("save_rules EXC:", type(exc).__name__, exc, flush=True)
        dialog._save_rule()
        print("STEP saved 1", flush=True)
        rules = BulkPricingService(session).rules_for_product(product.id)
        print("rules after save1:", [(r.quantity_threshold, r.special_price) for r in rules], flush=True)
        dialog.tier_rows[0].price_input.setValue(1_600)
        print("STEP price 1600, disc:", dialog.tier_rows[0].discount_input.value(), flush=True)
        dialog._save_rule()
        print("STEP saved 2", flush=True)
        rules = BulkPricingService(session).rules_for_product(product.id)
        print("rules after save2:", [(r.quantity_threshold, r.special_price, r.pricing_mode) for r in rules], flush=True)
        dialog.close()
        view.close()
        print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
