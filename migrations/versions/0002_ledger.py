"""Create accounts and an append-only paired-entry ledger."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE ledger_accounts (
            id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            account_type VARCHAR(20) NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            merchant_id VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_ledger_account_type
                CHECK (account_type IN ('ASSET', 'LIABILITY')),

            CONSTRAINT ck_ledger_account_currency
                CHECK (currency = 'USD')
        )
    """)

    op.execute("""
        INSERT INTO ledger_accounts (
            id, name, account_type, currency, merchant_id
        )
        VALUES
            (
                'processor-clearing-usd',
                'Processor clearing',
                'ASSET',
                'USD',
                NULL
            ),
            (
                'merchant-payable-demo-merchant-usd',
                'Demo merchant payable',
                'LIABILITY',
                'USD',
                'demo-merchant'
            )
    """)

    op.execute("""
        CREATE TABLE ledger_transactions (
            id UUID PRIMARY KEY,
            payment_id UUID NOT NULL,
            operation VARCHAR(32) NOT NULL,
            debit_account_id VARCHAR(128) NOT NULL,
            credit_account_id VARCHAR(128) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency VARCHAR(3) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT fk_ledger_payment
                FOREIGN KEY (payment_id)
                REFERENCES payments(id)
                ON DELETE RESTRICT,

            CONSTRAINT fk_ledger_debit_account
                FOREIGN KEY (debit_account_id)
                REFERENCES ledger_accounts(id)
                ON DELETE RESTRICT,

            CONSTRAINT fk_ledger_credit_account
                FOREIGN KEY (credit_account_id)
                REFERENCES ledger_accounts(id)
                ON DELETE RESTRICT,

            CONSTRAINT uq_ledger_payment_operation
                UNIQUE (payment_id, operation),

            CONSTRAINT ck_ledger_operation
                CHECK (operation = 'CAPTURE'),

            CONSTRAINT ck_ledger_amount
                CHECK (
                    amount_minor > 0
                    AND amount_minor <= 1000000000
                ),

            CONSTRAINT ck_ledger_currency
                CHECK (currency = 'USD'),

            CONSTRAINT ck_ledger_distinct_accounts
                CHECK (debit_account_id != credit_account_id)
        )
    """)

    op.execute("""
        CREATE INDEX ix_ledger_debit_account
        ON ledger_transactions (debit_account_id, created_at)
    """)

    op.execute("""
        CREATE INDEX ix_ledger_credit_account
        ON ledger_transactions (credit_account_id, created_at)
    """)

    op.execute("""
        CREATE VIEW ledger_entries AS
        SELECT
            id AS transaction_id,
            payment_id,
            debit_account_id AS account_id,
            'DEBIT'::TEXT AS side,
            amount_minor,
            currency,
            created_at
        FROM ledger_transactions

        UNION ALL

        SELECT
            id AS transaction_id,
            payment_id,
            credit_account_id AS account_id,
            'CREDIT'::TEXT AS side,
            amount_minor,
            currency,
            created_at
        FROM ledger_transactions
    """)

    op.execute("""
        CREATE FUNCTION reject_ledger_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Posted ledger transactions cannot be modified or removed';
        END;
        $$
    """)

    op.execute("""
        CREATE TRIGGER ledger_no_update_or_delete
        BEFORE UPDATE OR DELETE ON ledger_transactions
        FOR EACH ROW
        EXECUTE FUNCTION reject_ledger_mutation()
    """)

    op.execute("""
        CREATE TRIGGER ledger_no_truncate
        BEFORE TRUNCATE ON ledger_transactions
        FOR EACH STATEMENT
        EXECUTE FUNCTION reject_ledger_mutation()
    """)


def downgrade():
    op.execute("DROP VIEW ledger_entries")
    op.execute("DROP TABLE ledger_transactions")
    op.execute("DROP FUNCTION reject_ledger_mutation()")
    op.execute("DROP TABLE ledger_accounts")