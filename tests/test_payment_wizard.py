import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.secret_box import SecretBox
from app.models import PaymentWizardState, Role, User
from app.services.payment_wizard_service import (
    STATUS_ACTIVE,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    PaymentWizardService,
)
from app.ui.views.payment_wizard_view import PaymentWizardDialog


@pytest.fixture
def wizard_env(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner_role = Role(name="OWNER")
            cashier_role = Role(name="CASHIER")
            session.add_all([owner_role, cashier_role])
            session.flush()
            owner = User(
                username="owner",
                full_name="Owner",
                password_hash="x",
                role=owner_role,
            )
            cashier = User(
                username="cashier",
                full_name="Cashier",
                password_hash="x",
                role=cashier_role,
            )
            session.add_all([owner, cashier])
            session.flush()
            secret = SecretBox(tmp_path / "wizard.key")
            service = PaymentWizardService(session, secret)
            yield session, owner, cashier, service
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_service_roundtrip_encrypts_payload_and_bumps_status(wizard_env):
    session, owner, _cashier, service = wizard_env
    service.save(
        owner,
        method="QRIS_DANA",
        status=STATUS_NOT_STARTED,
        payload={"api_client_secret": "rahasia-sangat-sensitif"},
    )

    state = session.query(PaymentWizardState).filter_by(method="QRIS_DANA").one()
    assert "rahasia-sangat-sensitif" not in state.payload
    assert state.status == STATUS_IN_PROGRESS

    loaded = service.load_payload("QRIS_DANA")
    assert loaded["api_client_secret"] == "rahasia-sangat-sensitif"


def test_service_requires_owner(wizard_env):
    _session, _owner, cashier, service = wizard_env
    with pytest.raises(AuthorizationError):
        service.save(
            cashier,
            method="QRIS_DANA",
            status=STATUS_ACTIVE,
            payload={},
        )


def test_service_rejects_unknown_method_and_status(wizard_env):
    _session, owner, _cashier, service = wizard_env
    with pytest.raises(ValidationError):
        service.save(owner, method="PAYME", status=STATUS_ACTIVE, payload={})
    with pytest.raises(ValidationError):
        service.save(owner, method="QRIS_DANA", status="nonsense", payload={})


def test_test_connection_validates_required_fields(wizard_env):
    _session, _owner, _cashier, service = wizard_env
    ok, message = service.test_connection({})
    assert not ok
    assert "Partner ID" in message

    ok, message = service.test_connection({"api_partner_id": "P1"})
    assert not ok
    assert "Merchant ID" in message

    ok, message = service.test_connection(
        {"api_partner_id": "P1", "api_merchant_id": "M1"}
    )
    assert not ok
    assert "Private key" in message


def test_secret_box_roundtrip(tmp_path):
    box = SecretBox(tmp_path / "key.bin")
    token = box.encrypt({"a": "b"})
    assert box.decrypt(token) == {"a": "b"}
    assert box.decrypt("") == {}


def test_wizard_dialog_builds_ten_steps_and_progress(wizard_env, qt_app):
    _session, owner, _cashier, service = wizard_env
    dialog = PaymentWizardDialog("QRIS_DANA", owner, service)
    assert len(dialog.step_checks) == 10
    assert dialog.progress_label.text() == "0/10"
    assert dialog.progress.value() == 0

    for key in (
        "register_email",
        "business_name",
        "api_partner_id",
        "api_private_key",
        "test_result",
        "activation_confirmed",
    ):
        assert key in dialog.fields

    dialog.step_checks[0].setChecked(True)
    dialog.step_checks[4].setChecked(True)
    assert dialog.progress_label.text() == "2/10"
    assert dialog.progress.value() == 20
    dialog.close()


def test_wizard_dialog_save_and_reload_roundtrip(wizard_env, qt_app):
    _session, owner, _cashier, service = wizard_env
    dialog = PaymentWizardDialog("QRIS_DANA", owner, service)
    dialog.fields["register_email"].setText("toko@contoh.id")
    dialog.fields["api_merchant_id"].setText("MER-123")
    dialog.integration_qris.setChecked(True)
    dialog.step_checks[0].setChecked(True)
    dialog.step_checks[7].setChecked(True)
    dialog._save(closing=True)
    dialog.close()

    reloaded = PaymentWizardDialog("QRIS_DANA", owner, service)
    assert reloaded.fields["register_email"].text() == "toko@contoh.id"
    assert reloaded.fields["api_merchant_id"].text() == "MER-123"
    assert reloaded.integration_qris.isChecked()
    assert reloaded.step_checks[0].isChecked()
    assert reloaded.step_checks[7].isChecked()
    assert reloaded.progress_label.text() == "2/10"
    reloaded.close()


def test_midtrans_connection_validates_required_fields(wizard_env):
    _session, _owner, _cashier, service = wizard_env
    ok, message = service.test_connection({}, method="QRIS_MIDTRANS")
    assert not ok
    assert "Server Key" in message

    ok, message = service.test_connection(
        {"server_key": "SB-Mid-x"}, method="QRIS_MIDTRANS"
    )
    assert not ok
    assert "Client Key" in message


def test_bank_connection_manual_mode_validation(wizard_env):
    _session, _owner, _cashier, service = wizard_env
    ok, message = service.test_connection({"transfer_mode": "manual"}, method="BANK")
    assert not ok
    assert "Nama bank" in message

    ok, message = service.test_connection(
        {"transfer_mode": "manual", "bank_name": "BCA"}, method="BANK"
    )
    assert not ok
    assert "Nomor rekening" in message

    ok, message = service.test_connection(
        {"transfer_mode": "manual", "bank_name": "BCA", "account_number": "123"},
        method="BANK",
    )
    assert ok


def test_bank_connection_va_mode_validation(wizard_env):
    _session, _owner, _cashier, service = wizard_env
    ok, message = service.test_connection({"transfer_mode": "va"}, method="BANK")
    assert not ok
    assert "penyedia" in message.lower()

    ok, message = service.test_connection(
        {"transfer_mode": "va", "va_provider": "Penyedia lain"}, method="BANK"
    )
    assert not ok
    assert "Penyedia lain" in message

    ok, message = service.test_connection(
        {"transfer_mode": "va", "va_provider": "Midtrans Virtual Account"},
        method="BANK",
    )
    assert not ok
    assert "Server Key" in message


def test_midtrans_wizard_builds_ten_steps_and_progress(qt_app, wizard_env):
    _session, owner, _cashier, service = wizard_env
    dialog = PaymentWizardDialog("QRIS_MIDTRANS", owner, service)
    assert len(dialog.step_checks) == 10
    assert dialog.progress_label.text() == "0/10"
    for key in (
        "reg_email",
        "business_site",
        "qris_activated",
        "server_key",
        "client_key",
        "test_result",
        "production_confirmed",
    ):
        assert key in dialog.fields
    dialog.step_checks[5].setChecked(True)
    assert dialog.progress_label.text() == "1/10"
    dialog.close()


def test_midtrans_server_key_encrypted_at_rest(qt_app, wizard_env):
    session, owner, _cashier, service = wizard_env
    dialog = PaymentWizardDialog("QRIS_MIDTRANS", owner, service)
    dialog.fields["server_key"].setText("SB-Mid-server-rahasia")
    dialog.fields["client_key"].setText("SB-Mid-client")
    dialog._save(closing=True)
    dialog.close()

    state = session.query(PaymentWizardState).filter_by(method="QRIS_MIDTRANS").one()
    assert "SB-Mid-server-rahasia" not in state.payload
    assert state.status == STATUS_IN_PROGRESS

    reloaded = PaymentWizardDialog("QRIS_MIDTRANS", owner, service)
    assert reloaded.fields["server_key"].text() == "SB-Mid-server-rahasia"
    reloaded.close()


def test_bank_wizard_has_two_modes_and_switches_progress(qt_app, wizard_env):
    _session, owner, _cashier, service = wizard_env
    dialog = PaymentWizardDialog("BANK", owner, service)

    assert dialog.transfer_mode == "manual"
    assert len(dialog.step_checks) == 6
    assert dialog.progress_label.text() == "0/6"
    assert dialog.manual_container.isVisibleTo(dialog)
    assert not dialog.va_container.isVisibleTo(dialog)

    dialog.mode_va.setChecked(True)
    assert dialog.transfer_mode == "va"
    assert len(dialog.step_checks) == 8
    assert dialog.progress_label.text() == "0/8"
    assert not dialog.manual_container.isVisibleTo(dialog)
    assert dialog.va_container.isVisibleTo(dialog)

    dialog.step_checks[0].setChecked(True)
    assert dialog.progress_label.text() == "1/8"
    dialog.close()


def test_bank_wizard_keeps_data_for_both_modes_on_save(qt_app, wizard_env):
    session, owner, _cashier, service = wizard_env
    dialog = PaymentWizardDialog("BANK", owner, service)
    dialog.fields["bank_name"].setCurrentText("Mandiri")
    dialog.fields["account_number"].setText("99887766")
    dialog.step_checks[1].setChecked(True)

    dialog.mode_va.setChecked(True)
    dialog.fields["va_provider"].setCurrentText("Penyedia lain")
    dialog.fields["va_server_key"].setText("SB-Mid-server-va")
    dialog.step_checks[3].setChecked(True)
    dialog._save(closing=True)
    dialog.close()

    reloaded = PaymentWizardDialog("BANK", owner, service)
    assert reloaded.fields["bank_name"].currentText() == "Mandiri"
    assert reloaded.fields["account_number"].text() == "99887766"
    assert reloaded.fields["va_server_key"].text() == "SB-Mid-server-va"
    assert reloaded.transfer_mode == "va"
    assert reloaded.check_groups["steps_done_manual"][0].isChecked()
    assert reloaded.check_groups["steps_done_va"][2].isChecked()
    reloaded.close()

    state = session.query(PaymentWizardState).filter_by(method="BANK").one()
    assert "SB-Mid-server-va" not in state.payload


def test_all_wizard_methods_build_steps(qt_app, wizard_env):
    _session, owner, _cashier, service = wizard_env
    for method, expected in (
        ("QRIS_DANA", 10),
        ("QRIS_MIDTRANS", 10),
        ("BANK", 6),
    ):
        dialog = PaymentWizardDialog(method, owner, service)
        assert len(dialog.step_checks) == expected, method
        assert dialog.windowTitle().startswith("Wizard "), method
        dialog.close()
