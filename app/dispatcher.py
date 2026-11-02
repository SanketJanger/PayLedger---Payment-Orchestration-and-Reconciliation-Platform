import asyncio
import logging
import os
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from app.database import engine
from app.workflows import PaymentWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get(
    "TEMPORAL_ADDRESS",
    "temporal:7233",
)
TASK_QUEUE = "payledger-payments"


def load_unpublished_events() -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT id, payment_id
                FROM outbox_events
                WHERE published_at IS NULL
                  AND event_type = 'PAYMENT_REQUESTED'
                ORDER BY created_at, id
                LIMIT 50
            """)
        ).mappings().all()

        return [dict(row) for row in rows]


def mark_published(event_id: UUID):
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE outbox_events
                SET published_at = now()
                WHERE id = :event_id
                  AND published_at IS NULL
            """),
            {"event_id": event_id},
        )


async def deliver_event(client: Client, event: dict):
    payment_id = str(event["payment_id"])
    workflow_id = f"payment-{payment_id}"

    try:
        await client.start_workflow(
            PaymentWorkflow.run,
            payment_id,
            id=workflow_id,
            task_queue=TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            execution_timeout=timedelta(minutes=6),
            rpc_timeout=timedelta(seconds=10),
        )
        outcome = "started"

    except WorkflowAlreadyStartedError:
        outcome = "already_exists"

    # Any other start error leaves the event unpublished.
    await asyncio.to_thread(mark_published, event["id"])

    logger.info(
        "Outbox delivered: event_id=%s payment_id=%s workflow=%s outcome=%s",
        event["id"],
        payment_id,
        workflow_id,
        outcome,
    )


async def main():
    client = await Client.connect(TEMPORAL_ADDRESS)
    logger.info("Dispatcher connected to %s", TEMPORAL_ADDRESS)

    try:
        while True:
            try:
                events = await asyncio.to_thread(
                    load_unpublished_events
                )
            except Exception:
                logger.exception("Failed to load unpublished events")
                await asyncio.sleep(2)
                continue

            for event in events:
                try:
                    await deliver_event(client, event)
                except Exception:
                    logger.exception(
                        "Outbox delivery failed; event remains pending: %s",
                        event["id"],
                    )

            await asyncio.sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())