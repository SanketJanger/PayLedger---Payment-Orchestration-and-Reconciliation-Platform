from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection
from temporalio.exceptions import ApplicationError


def ensure_capture_posting(
    connection: Connection,
    payment: dict,
    *,
    require_existing: bool = False,
) -> None:
    """Caller must hold the payment row lock in this transaction."""

    debit_account = "processor-clearing-usd"
    credit_account = (
        f"merchant-payable-{payment['merchant_id']}-usd"
    )

    accounts = connection.execute(
        text("""
            SELECT id, account_type, currency, merchant_id
            FROM ledger_accounts
            WHERE id IN (:debit_account, :credit_account)
            ORDER BY id
            FOR SHARE
        """),
        {
            "debit_account": debit_account,
            "credit_account": credit_account,
        },
    ).mappings().all()

    by_id = {row["id"]: row for row in accounts}
    debit = by_id.get(debit_account)
    credit = by_id.get(credit_account)

    if (
        debit is None
        or credit is None
        or debit["account_type"] != "ASSET"
        or credit["account_type"] != "LIABILITY"
        or debit["currency"] != payment["currency"]
        or credit["currency"] != payment["currency"]
        or debit["merchant_id"] is not None
        or credit["merchant_id"] != payment["merchant_id"]
    ):
        raise ApplicationError(
            "Capture accounts do not match the payment",
            non_retryable=True,
        )

    expected = {
        "debit_account_id": debit_account,
        "credit_account_id": credit_account,
        "amount_minor": payment["amount_minor"],
        "currency": payment["currency"],
    }

    existing = connection.execute(
        text("""
            SELECT debit_account_id, credit_account_id,
                   amount_minor, currency
            FROM ledger_transactions
            WHERE payment_id = :payment_id
              AND operation = 'CAPTURE'
        """),
        {"payment_id": payment["id"]},
    ).mappings().one_or_none()

    if existing is not None:
        if any(existing[name] != value for name, value in expected.items()):
            raise ApplicationError(
                "Existing capture posting conflicts with payment",
                non_retryable=True,
            )
        return

    if require_existing:
        raise ApplicationError(
            "Successful payment has no capture posting; "
            "explicit ledger backfill is required",
            non_retryable=True,
        )

    connection.execute(
        text("""
            INSERT INTO ledger_transactions (
                id,
                payment_id,
                operation,
                debit_account_id,
                credit_account_id,
                amount_minor,
                currency
            )
            VALUES (
                :id,
                :payment_id,
                'CAPTURE',
                :debit_account_id,
                :credit_account_id,
                :amount_minor,
                :currency
            )
        """),
        {
            "id": uuid4(),
            "payment_id": payment["id"],
            **expected,
        },
    )