"""Baseline existing novel and daily answer tables

Revision ID: 18ae8b0fbedf
Revises: 
Create Date: 2026-10-23 01:35:11.359917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '18ae8b0fbedf'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "novels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("translator", sa.String(255), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("chapters", sa.Integer(), nullable=False),
        sa.Column("genres", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title"),
        sa.UniqueConstraint("url"),
    )

    op.create_table(
        "daily_answers",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False),
        sa.Column("answer_data", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["novels.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("daily_answers")
    op.drop_table("novels")
    