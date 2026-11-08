"""chat_messages.meta: persist answer flags (mode, not_in_kb, offer_watch) so reloaded threads keep them

Revision ID: b7c1d2e3f4a5
Revises: e08a33af5d2e
Create Date: 2026-11-08 14:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7c1d2e3f4a5"
down_revision = "e08a33af5d2e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "meta")
