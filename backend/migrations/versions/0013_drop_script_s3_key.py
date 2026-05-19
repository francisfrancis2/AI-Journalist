"""Drop script S3 key column

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("stories", "script_s3_key")


def downgrade() -> None:
    op.add_column("stories", sa.Column("script_s3_key", sa.String(1024), nullable=True))
