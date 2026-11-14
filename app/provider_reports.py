import hashlib
import json
from datetime import timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.database import engine


class ReportConflictError(ValueError):
    pass


class ReportCharge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    idempotency_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    amount_minor: int = Field(
        strict=True,
        gt=0,
        le=9_223_372_036_854_775_807,
    )
    currency: Literal["USD"]
    status: Literal["succeeded"]
    created_at: AwareDatetime


class ProviderReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    provider: Literal["simulator"]
    cutoff: AwareDatetime
    generated_at: AwareDatetime
    row_count: int = Field(strict=True, ge=0, le=10_000)
    charges: list[ReportCharge] = Field(max_length=10_000)


def validate_report(payload: dict) -> ProviderReport:
    report = ProviderReport.model_validate(payload)

    if report.row_count != len(report.charges):
        raise ValueError("Report row_count does not match charge count")

    if report.cutoff > report.generated_at - timedelta(seconds=60):
        raise ValueError("Report cutoff requires a 60-second grace period")

    charge_ids = set()
    keys = set()

    for charge in report.charges:
        if charge.id in charge_ids:
            raise ValueError("Duplicate charge ID in report")

        if charge.idempotency_key in keys:
            raise ValueError("Duplicate idempotency key in report")

        if charge.created_at >= report.cutoff:
            raise ValueError("Charge timestamp must precede report cutoff")

        charge_ids.add(charge.id)
        keys.add(charge.idempotency_key)

    return report


def report_hash(report: ProviderReport) -> str:
    # Equivalent timezone offsets and row orders produce the same hash.
    normalized = report.model_dump(mode="json")
    normalized["cutoff"] = report.cutoff.astimezone(
        timezone.utc
    ).isoformat()
    normalized["generated_at"] = report.generated_at.astimezone(
        timezone.utc
    ).isoformat()

    normalized["charges"] = []
    for charge in sorted(report.charges, key=lambda row: str(row.id)):
        row = charge.model_dump(mode="json")
        row["created_at"] = charge.created_at.astimezone(
            timezone.utc
        ).isoformat()
        normalized["charges"].append(row)

    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def import_provider_report(payload: dict) -> dict:
    report = validate_report(payload)
    digest = report_hash(report)

    with engine.begin() as connection:
        inserted = connection.execute(
            text("""
                INSERT INTO provider_reports (
                    id, provider, cutoff, generated_at,
                    row_count, payload_sha256
                )
                VALUES (
                    :id, :provider, :cutoff, :generated_at,
                    :row_count, :payload_sha256
                )
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """),
            {
                "id": report.report_id,
                "provider": report.provider,
                "cutoff": report.cutoff,
                "generated_at": report.generated_at,
                "row_count": report.row_count,
                "payload_sha256": digest,
            },
        ).scalar_one_or_none()

        if inserted is None:
            existing_hash = connection.execute(
                text("""
                    SELECT payload_sha256
                    FROM provider_reports
                    WHERE id = :id
                """),
                {"id": report.report_id},
            ).scalar_one()

            if existing_hash != digest:
                raise ReportConflictError(
                    "Report ID already exists with different content"
                )

            replayed = True
        else:
            if report.charges:
                connection.execute(
                    text("""
                        INSERT INTO provider_report_charges (
                            report_id, charge_id, idempotency_key,
                            amount_minor, currency, status, created_at
                        )
                        VALUES (
                            :report_id, :charge_id, :idempotency_key,
                            :amount_minor, :currency, :status, :created_at
                        )
                    """),
                    [
                        {
                            "report_id": report.report_id,
                            "charge_id": charge.id,
                            "idempotency_key": charge.idempotency_key,
                            "amount_minor": charge.amount_minor,
                            "currency": charge.currency,
                            "status": charge.status,
                            "created_at": charge.created_at,
                        }
                        for charge in report.charges
                    ],
                )

            replayed = False

    # Return only after the transaction commits.
    return {
        "report_id": str(report.report_id),
        "row_count": report.row_count,
        "replayed": replayed,
    }