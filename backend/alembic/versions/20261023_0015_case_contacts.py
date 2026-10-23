"""Contact details per case: reused in resumes, letters and application forms

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-23 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from nexscout.infrastructure.db.rls import disable_owner_rls, enable_owner_rls, grant_app

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "case_contacts",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "owner_user_id"],
            ["candidate_cases.id", "candidate_cases.owner_user_id"],
            name=op.f("fk_case_contacts_case_id_candidate_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("case_id", name=op.f("pk_case_contacts")),
    )
    enable_owner_rls("case_contacts")
    grant_app("case_contacts")


def downgrade() -> None:
    disable_owner_rls("case_contacts")
    op.drop_table("case_contacts")
