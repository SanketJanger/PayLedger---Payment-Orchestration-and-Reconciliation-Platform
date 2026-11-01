import os

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    func,
)

engine = create_engine(
    os.environ["DATABASE_URL"],
    pool_pre_ping=True,
    pool_timeout=3,
    connect_args={"connect_timeout": 3},
)

metadata = MetaData()

charges = Table(
    "charges",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("amount_minor", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("status", String(20), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("amount_minor > 0", name="positive_charge_amount"),
    CheckConstraint("currency = 'USD'", name="supported_currency"),
    CheckConstraint("status = 'succeeded'", name="supported_charge_status"),
)