"""Assistant conversations: consent to an online AI model is given per conversation

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-23 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexscout.infrastructure.db.rls import disable_owner_rls, enable_owner_rls, grant_app

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "owner_user_id"],
            ["candidate_cases.id", "candidate_cases.owner_user_id"],
            name=op.f("fk_chat_conversations_case_id_candidate_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_conversations")),
    )
    op.create_index(
        "ix_chat_conversations_case_created", "chat_conversations", ["case_id", "created_at"]
    )
    enable_owner_rls("chat_conversations")
    grant_app("chat_conversations")

    op.add_column("chat_messages", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.add_column("chat_messages", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_chat_messages_conversation_id_chat_conversations"),
        "chat_messages",
        "chat_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(op.f("uq_chat_messages_run_id"), "chat_messages", ["run_id"])
    op.create_index(
        "ix_chat_messages_conversation_seq", "chat_messages", ["conversation_id", "seq"]
    )

    # Earlier messages become each case's first conversation (migrations run as the owner role,
    # which isn't subject to row security).
    op.execute(
        "INSERT INTO chat_conversations (id, owner_user_id, case_id, created_at) "
        "SELECT gen_random_uuid(), owner_user_id, case_id, min(created_at) "
        "FROM chat_messages GROUP BY owner_user_id, case_id"
    )
    op.execute(
        "UPDATE chat_messages m SET conversation_id = c.id FROM chat_conversations c "
        "WHERE c.case_id = m.case_id AND c.owner_user_id = m.owner_user_id"
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_seq", table_name="chat_messages")
    op.drop_constraint(op.f("uq_chat_messages_run_id"), "chat_messages", type_="unique")
    op.drop_constraint(
        op.f("fk_chat_messages_conversation_id_chat_conversations"),
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_column("chat_messages", "run_id")
    op.drop_column("chat_messages", "conversation_id")
    disable_owner_rls("chat_conversations")
    op.drop_index("ix_chat_conversations_case_created", table_name="chat_conversations")
    op.drop_table("chat_conversations")
