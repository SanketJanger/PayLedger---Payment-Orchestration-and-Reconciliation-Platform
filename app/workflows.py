from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class InfrastructureCheckWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        return f"Worker executed workflow: {message}"


@workflow.defn
class PaymentWorkflow:
    @workflow.run
    async def run(self, payment_id: str) -> str:
        return await workflow.execute_activity(
            "process_payment",
            payment_id,
            result_type=str,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=20),
                maximum_attempts=5,
            ),
        )