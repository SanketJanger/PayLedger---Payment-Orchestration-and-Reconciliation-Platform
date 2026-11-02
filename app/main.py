import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.database import engine
from app.payments import router as payments_router

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await run_in_threadpool(engine.dispose)


app = FastAPI(
    title="PayLedger",
    description="Payment orchestration and reconciliation platform.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(payments_router)


@app.get("/health/live", tags=["Health"])
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", tags=["Health"])
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Database readiness check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None

    return {
        "status": "ready",
        "database": "reachable",
    }