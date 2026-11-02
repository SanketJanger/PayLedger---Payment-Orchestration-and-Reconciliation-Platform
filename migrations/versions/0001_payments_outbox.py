"""Create payments and outbox tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("order_id", sa.String(128), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "provider_charge_id",
            sa.String(36),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint(
            "merchant_id",
            "idempotency_key",
            name="uq_payments_merchant_idempotency",
        ),
        sa.UniqueConstraint(
            "provider_charge_id",
            name="uq_payments_provider_charge",
        ),
        sa.CheckConstraint(
            "amount_minor > 0 AND amount_minor <= 1000000000",
            name="ck_payments_amount",
        ),
        sa.CheckConstraint(
            "currency = 'USD'",
            name="ck_payments_currency",
        ),
        sa.CheckConstraint(
            "status IN "
            "('PENDING', 'PROCESSING', 'UNKNOWN', 'SUCCEEDED', 'FAILED')",
            name="ck_payments_status",
        ),
        sa.CheckConstraint(
            "status != 'SUCCEEDED' OR provider_charge_id IS NOT NULL",
            name="ck_payments_success_provider_reference",
        ),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_outbox_payment",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "payment_id",
            "event_type",
            name="uq_outbox_payment_event",
        ),
        sa.CheckConstraint(
            "event_type = 'PAYMENT_REQUESTED'",
            name="ck_outbox_event_type",
        ),
    )

    op.create_index(
        "ix_outbox_unpublished",
        "outbox_events",
        ["created_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade():
    op.drop_index(
        "ix_outbox_unpublished",
        table_name="outbox_events",
    )
    op.drop_table("outbox_events")
    op.drop_table("payments")