import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from app.workflows import InfrastructureCheckWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get(
    "TEMPORAL_ADDRESS",
    "temporal:7233",
)
TASK_QUEUE = "payledger-payments"


async def main():
    client = await Client.connect(TEMPORAL_ADDRESS)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[InfrastructureCheckWorkflow],
    )

    logger.info(
        "Worker connected to %s; polling task queue %s",
        TEMPORAL_ADDRESS,
        TASK_QUEUE,
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())