import os

from sqlalchemy import create_engine

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=3,
    connect_args={
        "connect_timeout": 3,
        "options": "-c statement_timeout=3000",
    },
)