"""Store reconciliation runs and their findings."""

from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE reconciliation_runs (
            id UUID PRIMARY KEY,
            report_id UUID NOT NULL,
            rules_version VARCHAR(32) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            payments_checked INTEGER NOT NULL,
            charges_checked INTEGER NOT NULL,
            finding_count INTEGER NOT NULL,

            CONSTRAINT fk_reconciliation_report
                FOREIGN KEY (report_id)
                REFERENCES provider_reports(id)
                ON DELETE RESTRICT,

            CONSTRAINT ck_reconciliation_times
                CHECK (completed_at >= observed_at),

            CONSTRAINT ck_reconciliation_counts
                CHECK (
                    payments_checked >= 0
                    AND charges_checked >= 0
                    AND finding_count >= 0
                ),

            CONSTRAINT ck_reconciliation_rules
                CHECK (char_length(rules_version) > 0)
        )
    """)

    op.execute("""
        CREATE TABLE reconciliation_findings (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL,
            finding_type VARCHAR(40) NOT NULL,
            subject_key VARCHAR(160) NOT NULL,
            payment_id UUID,
            provider_charge_id UUID,
            evidence JSONB NOT NULL,

            CONSTRAINT fk_reconciliation_finding_run
                FOREIGN KEY (run_id)
                REFERENCES reconciliation_runs(id)
                ON DELETE RESTRICT,

            CONSTRAINT uq_reconciliation_finding
                UNIQUE (run_id, finding_type, subject_key),

            CONSTRAINT ck_reconciliation_finding_type
                CHECK (
                    finding_type IN (
                        'UNMATCHED_PROVIDER_CHARGE',
                        'MISSING_LOCAL_PAYMENT',
                        'UNRESOLVED_PAYMENT',
                        'PAYMENT_MISMATCH',
                        'MISSING_PROVIDER_CHARGE',
                        'MISSING_LEDGER_CAPTURE',
                        'LEDGER_MISMATCH'
                    )
                ),

            CONSTRAINT ck_reconciliation_subject
                CHECK (char_length(subject_key) > 0),

            CONSTRAINT ck_reconciliation_evidence
                CHECK (jsonb_typeof(evidence) = 'object')
        )
    """)

    op.execute("""
        CREATE INDEX ix_reconciliation_runs_report
        ON reconciliation_runs (report_id, observed_at)
    """)

    op.execute("""
        CREATE INDEX ix_reconciliation_findings_payment
        ON reconciliation_findings (payment_id)
        WHERE payment_id IS NOT NULL
    """)

    op.execute("""
        CREATE FUNCTION reject_reconciliation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Reconciliation history cannot be modified or removed';
        END;
        $$
    """)

    for table in ("reconciliation_runs", "reconciliation_findings"):
        op.execute(f"""
            CREATE TRIGGER {table}_no_update_or_delete
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION reject_reconciliation_mutation()
        """)

        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION reject_reconciliation_mutation()
        """)


def downgrade():
    op.execute("DROP TABLE reconciliation_findings")
    op.execute("DROP TABLE reconciliation_runs")
    op.execute("DROP FUNCTION reject_reconciliation_mutation()")