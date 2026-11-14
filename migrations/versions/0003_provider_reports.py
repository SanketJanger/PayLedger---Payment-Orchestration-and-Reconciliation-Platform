"""Store immutable provider reports and their charge rows."""

from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE provider_reports (
            id UUID PRIMARY KEY,
            provider VARCHAR(32) NOT NULL,
            cutoff TIMESTAMPTZ NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            row_count INTEGER NOT NULL,
            payload_sha256 VARCHAR(64) NOT NULL,

            CONSTRAINT ck_report_provider
                CHECK (provider = 'simulator'),

            CONSTRAINT ck_report_row_count
                CHECK (row_count BETWEEN 0 AND 10000),

            CONSTRAINT ck_report_cutoff
                CHECK (
                    cutoff <= generated_at - INTERVAL '60 seconds'
                ),

            CONSTRAINT ck_report_hash
                CHECK (payload_sha256 ~ '^[0-9a-f]{64}$')
        )
    """)

    op.execute("""
        CREATE TABLE provider_report_charges (
            report_id UUID NOT NULL,
            charge_id UUID NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency VARCHAR(3) NOT NULL,
            status VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,

            PRIMARY KEY (report_id, charge_id),

            CONSTRAINT fk_report_charge_report
                FOREIGN KEY (report_id)
                REFERENCES provider_reports(id)
                ON DELETE RESTRICT,

            CONSTRAINT uq_report_charge_key
                UNIQUE (report_id, idempotency_key),

            CONSTRAINT ck_report_charge_key
                CHECK (
                    char_length(idempotency_key) BETWEEN 1 AND 128
                    AND idempotency_key ~ '^[A-Za-z0-9_-]+$'
                ),

            CONSTRAINT ck_report_charge_amount
                CHECK (amount_minor > 0),

            CONSTRAINT ck_report_charge_currency
                CHECK (currency = 'USD'),

            CONSTRAINT ck_report_charge_status
                CHECK (status = 'succeeded')
        )
    """)

    op.execute("""
        CREATE INDEX ix_provider_reports_cutoff
        ON provider_reports (provider, cutoff, imported_at)
    """)

    op.execute("""
        CREATE FUNCTION reject_provider_report_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Imported provider reports cannot be modified or removed';
        END;
        $$
    """)

    for table in ("provider_reports", "provider_report_charges"):
        op.execute(f"""
            CREATE TRIGGER {table}_no_update_or_delete
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION reject_provider_report_mutation()
        """)

        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION reject_provider_report_mutation()
        """)


def downgrade():
    op.execute("DROP TABLE provider_report_charges")
    op.execute("DROP TABLE provider_reports")
    op.execute("DROP FUNCTION reject_provider_report_mutation()")