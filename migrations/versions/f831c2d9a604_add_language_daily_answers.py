from alembic import op

revision = "f831c2d9a604"
down_revision = "d13dced0b535"
branch_labels = None
depends_on = None


def upgrade():
    # Existing local databases may already have this table from pool setup.
    op.execute("""
        CREATE TABLE IF NOT EXISTS language_daily_answers (
            day DATE NOT NULL,
            language VARCHAR(2) NOT NULL,
            novel_id INTEGER NOT NULL
                REFERENCES novels(id) ON DELETE RESTRICT,
            answer_data JSONB NOT NULL,
            PRIMARY KEY (day, language)
        )
    """)


def downgrade():
    op.drop_table("language_daily_answers")