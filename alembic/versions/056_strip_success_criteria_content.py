"""Strip Success Criteria content from stored versions (CR-017 cleanup).

Revision ID: 056
Revises: 055
Create Date: 2025-11-30

Migration 055 converted ## Success Criteria to ### Success Criteria headers,
but the content remained in stored versions. Since those ACs are now in the
database and get injected on read, we need to strip the duplicate content.

This migration:
1. Finds all versions with ### Success Criteria sections
2. Strips the content (but not the header) from those sections
3. The AC injection will add the content back with current met status
"""
from typing import Sequence, Union
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision: str = '056'
down_revision: Union[str, None] = '055'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def strip_success_criteria_content(content: str) -> tuple[str, bool]:
    """Strip checkbox content from ### Success Criteria sections.

    Removes the checkbox lines but keeps the header for the injection to use.
    Actually, we should remove the entire section since injection rebuilds it.

    Returns (updated_content, was_changed).
    """
    if not content:
        return content, False

    # Pattern to match ### Success Criteria section and its checkbox content
    # up until the next ## or ### or # header or end of string
    pattern = r'(###\s+Success\s+Criteria\s*\n)(.*?)(?=\n##(?!#)|\n###|\n#\s|\Z)'

    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if not match:
        return content, False

    section_content = match.group(2)

    # Check if section has checkboxes (if not, nothing to strip)
    if not re.search(r'-\s*\[[ xX]\]', section_content):
        return content, False

    # Remove the entire ### Success Criteria section since injection will rebuild it
    # The section is part of AC section content now
    updated = content[:match.start()] + content[match.end():]

    # Clean up any double blank lines we might have created
    updated = re.sub(r'\n{3,}', '\n\n', updated)

    return updated, updated != content


def upgrade() -> None:
    """Strip Success Criteria content that's now in AC table."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Find all versions with ### Success Criteria
    versions = session.execute(sa.text("""
        SELECT id, content
        FROM requirement_versions
        WHERE content IS NOT NULL
        AND content ~* '###\\s+Success\\s+Criteria'
    """)).fetchall()

    stripped_count = 0

    for version_id, content in versions:
        updated_content, was_changed = strip_success_criteria_content(content)
        if was_changed:
            session.execute(sa.text("""
                UPDATE requirement_versions
                SET content = :content
                WHERE id = :version_id
            """), {'content': updated_content, 'version_id': version_id})
            stripped_count += 1

    session.commit()
    print(f"Migration 056: Stripped Success Criteria content from {stripped_count} versions")


def downgrade() -> None:
    """Cannot restore stripped content - would need to rebuild from AC table."""
    print("WARNING: Cannot restore stripped Success Criteria content.")
