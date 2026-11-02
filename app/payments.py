from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/payments", tags=["Payments"])

# Local development only; replace with authenticated merchant identity.
DEMO_MERCHANT_ID = "demo-merchant"


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ]
    amount_minor: Annotated[
        int,
        Field(strict=True, gt=0, le=1_000_000_000),
    ]
    currency: Literal["USD"]


class PaymentResponse(BaseModel):
    id: UUID
    order_id: str
    amount_minor: int
    currency: Literal["USD"]
    status: Literal[
        "PENDING",
        "PROCESSING",
        "UNKNOWN",
        "SUCCEEDED",
        "FAILED",
    ]
    provider_charge_id: str | None
    created_at: datetime
    updated_at: datetime


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


@router.post("", response_model=PaymentResponse, status_code=202)
def create_payment(
    payload: PaymentRequest,
    response: Response,
    idempotency_key: IdempotencyKey,
):
    with engine.begin() as connection:
        inserted = connection.execute(
            text("""
                INSERT INTO payments (
                    id,
                    merchant_id,
                    idempotency_key,
                    order_id,
                    amount_minor,
                    currency
                )
                VALUES (
                    :id,
                    :merchant_id,
                    :idempotency_key,
                    :order_id,
                    :amount_minor,
                    :currency
                )
                ON CONFLICT ON CONSTRAINT
                    uq_payments_merchant_idempotency
                DO NOTHING
                RETURNING *
            """),
            {
                "id": uuid4(),
                "merchant_id": DEMO_MERCHANT_ID,
                "idempotency_key": idempotency_key,
                **payload.model_dump(),
            },
        ).mappings().one_or_none()

        if inserted is not None:
            payment = dict(inserted)

            connection.execute(
                text("""
                    INSERT INTO outbox_events (
                        id,
                        payment_id,
                        event_type
                    )
                    VALUES (
                        :id,
                        :payment_id,
                        'PAYMENT_REQUESTED'
                    )
                """),
                {
                    "id": uuid4(),
                    "payment_id": payment["id"],
                },
            )

            replayed = False
        else:
            existing = connection.execute(
                text("""
                    SELECT *
                    FROM payments
                    WHERE merchant_id = :merchant_id
                      AND idempotency_key = :idempotency_key
                """),
                {
                    "merchant_id": DEMO_MERCHANT_ID,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().one()

            if any(
                existing[field] != value
                for field, value in payload.model_dump().items()
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Idempotency key was already used "
                        "with different payment details"
                    ),
                )

            payment = dict(existing)
            replayed = True

    # Both inserts have committed before we acknowledge acceptance.
    response.status_code = 200 if replayed else 202
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    response.headers["Location"] = f"/payments/{payment['id']}"

    return payment


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: UUID):
    with engine.connect() as connection:
        payment = connection.execute(
            text("""
                SELECT *
                FROM payments
                WHERE id = :payment_id
                  AND merchant_id = :merchant_id
            """),
            {
                "payment_id": payment_id,
                "merchant_id": DEMO_MERCHANT_ID,
            },
        ).mappings().one_or_none()

        if payment is None:
            raise HTTPException(
                status_code=404,
                detail="Payment not found",
            )

        return dict(payment)