import os
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.database import engine

PROVIDER_URL = os.environ["PROVIDER_URL"].rstrip("/")

# Local provider-simulator setting; default behavior has no delay.
PROVIDER_RESPONSE_DELAY_SECONDS = int(
    os.environ.get("PROVIDER_RESPONSE_DELAY_SECONDS", "0")
)

if not 0 <= PROVIDER_RESPONSE_DELAY_SECONDS <= 10:
    raise ValueError("Provider response delay must be between 0 and 10 seconds")

class ProviderCharge(BaseModel):
    id: UUID
    amount_minor: int = Field(strict=True, gt=0)
    currency: Literal["USD"]
    status: Literal["succeeded"]


def mark_unknown(payment_id: UUID):
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE payments
                SET status = 'UNKNOWN', updated_at = now()
                WHERE id = :id
                  AND status IN ('PENDING', 'PROCESSING', 'UNKNOWN')
            """),
            {"id": payment_id},
        )


@activity.defn
def process_payment(payment_id: str) -> str:
    payment_uuid = UUID(payment_id)

    # Lock only while reading/updating local state.
    with engine.begin() as connection:
        row = connection.execute(
            text("""
                SELECT *
                FROM payments
                WHERE id = :id
                FOR UPDATE
            """),
            {"id": payment_uuid},
        ).mappings().one_or_none()

        if row is None:
            raise ApplicationError(
                "Payment does not exist",
                non_retryable=True,
            )

        payment = dict(row)

        if payment["status"] == "SUCCEEDED":
            return payment["provider_charge_id"]

        if payment["status"] == "FAILED":
            raise ApplicationError(
                "Payment is already marked failed",
                non_retryable=True,
            )

        connection.execute(
            text("""
                UPDATE payments
                SET status = 'PROCESSING', updated_at = now()
                WHERE id = :id
            """),
            {"id": payment_uuid},
        )

    # No database transaction is held during the network request.
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.post(
                f"{PROVIDER_URL}/charges",
                headers={
                    "Idempotency-Key": f"payment-{payment_uuid}",
                    "X-Simulate-Response-Delay-Seconds": str(
                        PROVIDER_RESPONSE_DELAY_SECONDS
                    ),
                },
                json={
                    "amount_minor": payment["amount_minor"],
                    "currency": payment["currency"],
                },
            )
    except httpx.RequestError as exc:
        mark_unknown(payment_uuid)

        activity.logger.warning(
            "Provider outcome unknown: payment_id=%s attempt=%s error=%s",
            payment_id,
            activity.info().attempt,
            type(exc).__name__,
        )

        raise ApplicationError(
            "Provider outcome unknown after network error"
        ) from exc

    if response.status_code not in (200, 201):
        mark_unknown(payment_uuid)

        retryable = (
            response.status_code in (408, 429)
            or response.status_code >= 500
        )

        raise ApplicationError(
            f"Unexpected provider HTTP status: {response.status_code}",
            non_retryable=not retryable,
        )

    try:
        charge = ProviderCharge.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        mark_unknown(payment_uuid)
        raise ApplicationError(
            "Invalid provider response",
            non_retryable=True,
        ) from exc

    if (
        charge.amount_minor != payment["amount_minor"]
        or charge.currency != payment["currency"]
    ):
        mark_unknown(payment_uuid)
        raise ApplicationError(
            "Provider response does not match requested payment",
            non_retryable=True,
        )

    charge_id = str(charge.id)

    with engine.begin() as connection:
        current = connection.execute(
            text("""
                SELECT status, provider_charge_id
                FROM payments
                WHERE id = :id
                FOR UPDATE
            """),
            {"id": payment_uuid},
        ).mappings().one()

        if current["status"] == "SUCCEEDED":
            if current["provider_charge_id"] != charge_id:
                raise ApplicationError(
                    "Conflicting provider charge IDs",
                    non_retryable=True,
                )
            return charge_id

        if current["status"] == "FAILED":
            raise ApplicationError(
                "Payment became failed during processing",
                non_retryable=True,
            )

        connection.execute(
            text("""
                UPDATE payments
                SET status = 'SUCCEEDED',
                    provider_charge_id = :charge_id,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": payment_uuid,
                "charge_id": charge_id,
            },
        )

    return charge_id