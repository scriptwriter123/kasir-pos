from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models import (
    Account,
    FinancialSettings,
    JournalEntry,
    JournalLine,
    Role,
    User,
)
from app.services.financial_service import FinancialService


@pytest.fixture
def finance_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner_role = Role(name="OWNER")
            session.add(owner_role)
            session.flush()
            owner = User(
                username="owner",
                full_name="Test Owner",
                password_hash="unused",
                role=owner_role,
            )
            accounts = [
                Account(
                    code="1000",
                    name="Kas",
                    account_type="ASSET",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="1010",
                    name="Bank",
                    account_type="ASSET",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="1200",
                    name="Persediaan",
                    account_type="ASSET",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="2000",
                    name="Hutang Usaha",
                    account_type="LIABILITY",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="3000",
                    name="Modal Pemilik",
                    account_type="EQUITY",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="3100",
                    name="Saldo Awal",
                    account_type="EQUITY",
                    is_active=True,
                    is_system=True,
                ),
                Account(
                    code="6100",
                    name="Beban Sewa",
                    account_type="EXPENSE",
                    is_active=True,
                    is_system=False,
                ),
            ]
            session.add_all([owner, *accounts])
            session.flush()
            yield session, owner, {account.code: account for account in accounts}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_opening_expense_partial_payments_and_reports(finance_session):
    session, owner, accounts = finance_session
    service = FinancialService(session)
    assert service.settings() is None

    start_date = date.today()
    service.initialize(
        owner,
        start_date,
        {
            accounts["1000"].id: 100_000,
            accounts["1200"].id: 50_000,
            accounts["3000"].id: 150_000,
        },
    )

    expense = service.create_expense(
        owner,
        account_id=accounts["6100"].id,
        amount=30_000,
        incurred_at=datetime.now().astimezone(),
        payee="Pemilik Ruko",
        description="Sewa toko",
        due_date=start_date + timedelta(days=14),
        initial_payment=10_000,
        payment_account_id=accounts["1000"].id,
        payment_method="CASH",
    )
    service.record_expense_payment(
        owner,
        expense.id,
        20_000,
        accounts["1000"].id,
        "CASH",
    )

    assert expense.paid_amount == expense.amount == 30_000
    assert service.financial_report(
        "profit_loss", start_date, start_date
    )["net_income"] == -30_000
    balance_sheet = service.financial_report(
        "balance_sheet", start_date, start_date
    )
    assert balance_sheet["assets"] == 120_000
    assert balance_sheet["liabilities"] == 0
    assert balance_sheet["equity"] == 120_000
    assert balance_sheet["difference"] == 0

    cash_flow = service.financial_report("cash_flow", start_date, start_date)
    assert cash_flow["opening_cash"] == 100_000
    assert cash_flow["cash_out"] == 30_000
    assert cash_flow["closing_cash"] == 70_000

    trial_balance = service.financial_report(
        "trial_balance", start_date, start_date
    )
    assert trial_balance["debit_total"] == trial_balance["credit_total"]

    entries = list(session.scalars(select(JournalEntry)))
    assert entries
    for entry in entries:
        lines = list(
            session.scalars(
                select(JournalLine).where(
                    JournalLine.journal_entry_id == entry.id
                )
            )
        )
        assert sum(line.debit for line in lines) == sum(
            line.credit for line in lines
        )


def test_financial_settings_read_does_not_initialize_books(finance_session):
    session, _owner, _accounts = finance_session
    service = FinancialService(session)

    assert service.settings() is None
    assert session.get(FinancialSettings, 1) is None


def test_initialization_rejects_future_start_date(finance_session):
    _session, owner, _accounts = finance_session
    service = FinancialService(_session)

    with pytest.raises(ValidationError, match="masa depan"):
        service.initialize(
            owner,
            date.today() + timedelta(days=1),
            {},
        )


def test_expense_payment_status_lifecycle(finance_session):
    session, owner, accounts = finance_session
    service = FinancialService(session)
    start_date = date.today()
    service.initialize(owner, start_date, {accounts["1000"].id: 1_000_000})

    def make(amount, initial, status, due=True):
        return service.create_expense(
            owner,
            account_id=accounts["6100"].id,
            amount=amount,
            incurred_at=datetime.now().astimezone(),
            payee="Vendor",
            description="Beban operasional",
            due_date=start_date + timedelta(days=7) if due else None,
            initial_payment=initial,
            payment_account_id=(
                accounts["1000"].id if initial else None
            ),
            payment_method="CASH",
            payment_status=status,
        )

    hutang = make(50_000, 0, "HUTANG")
    assert hutang.payment_status == "HUTANG"
    assert hutang.paid_amount == 0

    # DP dari tab Catat selalu menyertakan Jumlah DP (> 0, < total).
    dp = make(80_000, 25_000, "DP")
    assert dp.payment_status == "DP"
    assert dp.paid_amount == 25_000

    cash = make(20_000, 20_000, "CASH", due=False)
    assert cash.payment_status == "CASH"
    assert cash.paid_amount == 20_000

    # Status tidak konsisten dengan pembayaran -> ditolak.
    with pytest.raises(ValidationError, match="lunas"):
        make(20_000, 0, "CASH")
    with pytest.raises(ValidationError, match="Hutang"):
        make(20_000, 5_000, "HUTANG")
    with pytest.raises(ValidationError, match="Jumlah DP"):
        make(20_000, 0, "DP")

    # Pembayaran sebagian mempertahankan status; pelunasan -> CASH.
    partial = service.record_expense_payment(
        owner, hutang.id, 30_000, accounts["1000"].id, "CASH"
    )
    assert partial.payment_status == "HUTANG"
    assert partial.paid_amount == 30_000
    settled = service.record_expense_payment(
        owner, hutang.id, 20_000, accounts["1000"].id, "CASH"
    )
    assert settled.payment_status == "CASH"
    assert settled.paid_amount == 50_000

    dp_partial = service.record_expense_payment(
        owner, dp.id, 30_000, accounts["1000"].id, "CASH"
    )
    assert dp_partial.payment_status == "DP"
    assert dp_partial.paid_amount == 55_000
    dp_settled = service.record_expense_payment(
        owner, dp.id, 25_000, accounts["1000"].id, "CASH"
    )
    assert dp_settled.payment_status == "CASH"
    assert dp_settled.paid_amount == 80_000
