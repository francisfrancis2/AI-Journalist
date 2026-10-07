"""Drop the confidence score from generated ideas.

The score was a derived heuristic (0.48 + 0.06 per domain + 0.03 per signal),
not a measured probability, and surfacing it as "N% confidence" implied a
precision the number never had.

Revision ID: 0021
Revises: 0020
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("generated_ideas", "confidence")


def downgrade() -> None:
    op.add_column(
        "generated_ideas",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
    )
