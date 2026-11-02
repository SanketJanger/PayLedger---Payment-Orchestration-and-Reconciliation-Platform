import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app.activities import process_payment
from app.database import engine
from app.workflows import (
    InfrastructureCheckWorkflow,
    PaymentWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get(
    "TEMPORAL_ADDRESS",
    "temporal:7233",
)
TASK_QUEUE = "payledger-payments"


async def main():
    client = await Client.connect(TEMPORAL_ADDRESS)

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            worker = Worker(
                client,
                task_queue=TASK_QUEUE,
                workflows=[
                    InfrastructureCheckWorkflow,
                    PaymentWorkflow,
                ],
                activities=[process_payment],
                activity_executor=executor,
                max_concurrent_activities=5,
            )

            logger.info(
                "Worker connected to %s; polling %s",
                TEMPORAL_ADDRESS,
                TASK_QUEUE,
            )

            await worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())