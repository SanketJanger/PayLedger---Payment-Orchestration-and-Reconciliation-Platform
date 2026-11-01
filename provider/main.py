import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool

from provider.database import charges, engine, metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_in_threadpool(metadata.create_all, engine)
    try:
        yield
    finally:
        await run_in_threadpool(engine.dispose)


app = FastAPI(
    title="PayLedger Provider Simulator",
    version="0.1.0",
    lifespan=lifespan,
)


class ChargeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: Annotated[
        int,
        Field(strict=True, gt=0, le=1_000_000_000),
    ]
    currency: Literal["USD"]


class ChargeResponse(BaseModel):
    id: UUID
    amount_minor: int
    currency: Literal["USD"]
    status: Literal["succeeded"]
    created_at: datetime


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.post("/charges", response_model=ChargeResponse, status_code=201)
def create_charge(
    payload: ChargeRequest,
    response: Response,
    idempotency_key: IdempotencyKey,
    simulate_response_delay_seconds: Annotated[
        int,
        Header(
            alias="X-Simulate-Response-Delay-Seconds",
            ge=0,
            le=10,
        ),
    ] = 0,
):
    statement = (
        insert(charges)
        .values(
            id=str(uuid4()),
            idempotency_key=idempotency_key,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            status="succeeded",
        )
        .on_conflict_do_nothing(
            index_elements=[charges.c.idempotency_key]
        )
        .returning(charges)
    )

    with engine.begin() as connection:
        inserted = connection.execute(statement).mappings().one_or_none()

        if inserted is not None:
            result = dict(inserted)
            replayed = False
        else:
            existing = connection.execute(
                select(charges).where(
                    charges.c.idempotency_key == idempotency_key
                )
            ).mappings().one()

            if (
                existing["amount_minor"] != payload.amount_minor
                or existing["currency"] != payload.currency
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Idempotency key was already used "
                        "with different payment details"
                    ),
                )

            result = dict(existing)
            replayed = True

    # The transaction has committed before we return a response.
    
    # Delay only a newly created charge, after its transaction commits.
    if not replayed and simulate_response_delay_seconds:
        time.sleep(simulate_response_delay_seconds)

    response.status_code = 200 if replayed else 201
    response.headers["Idempotency-Replayed"] = str(replayed).lower()

    return result


@app.get("/charges/lookup", response_model=ChargeResponse)
def lookup_charge(
    idempotency_key: Annotated[
        str,
        Query(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
):
    with engine.connect() as connection:
        existing = connection.execute(
            select(charges).where(
                charges.c.idempotency_key == idempotency_key
            )
        ).mappings().one_or_none()

        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Charge not found",
            )

        return dict(existing)