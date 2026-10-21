import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from app.hardware.printer import ReceiptPrinter


@pytest.fixture
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def sample_receipt():
    return {
        "store_name": "Toko Contoh",
        "invoice_no": "POS-20261009-ABC12345",
        "created_at": datetime.now(timezone.utc).astimezone().strftime(
            "%d-%m-%Y %H:%M:%S"
        ),
        "cashier_name": "Kasir",
        "items": [
            {
                "sku": "SKU-001",
                "name": "Mi Instan",
                "qty": 2,
                "unit_price": 3500,
                "line_total": 7000,
            }
        ],
        "subtotal": 7000,
        "discount": 0,
        "tax": 0,
        "total": 7000,
        "payment_method": "Tunai",
        "paid": 10000,
        "change": 3000,
    }


def test_receipt_html_contains_sale_details_and_escapes_user_content():
    receipt = sample_receipt()
    receipt["store_name"] = "<Toko & Contoh>"

    html = ReceiptPrinter.format_receipt_html(receipt)

    assert "&lt;Toko &amp; Contoh&gt;" in html
    assert "POS-20261009-ABC12345" in html
    assert "Mi Instan" in html
    assert "Rp 7.000,00" in html
    assert "Rp 3.000,00" in html


def test_receipt_can_be_saved_as_80mm_pdf(tmp_path, qt_app):
    output_file = tmp_path / "receipt.pdf"

    saved_file = ReceiptPrinter().save_pdf(sample_receipt(), output_file)

    assert saved_file == output_file
    assert saved_file.is_file()
    assert saved_file.read_bytes().startswith(b"%PDF-")
    assert saved_file.stat().st_size > 500
