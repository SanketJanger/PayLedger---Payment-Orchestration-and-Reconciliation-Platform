from temporalio import workflow


@workflow.defn
class InfrastructureCheckWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        return f"Worker executed workflow: {message}"