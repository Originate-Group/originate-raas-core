"""Strip ACs from content and backfill categories (CR-017 DRY).

Revision ID: 054
Revises: 053
Create Date: 2025-11-30

CR-017 DRY Migration: Completes the DRY implementation by:
1. Backfilling category field on existing acceptance_criteria records
2. Stripping AC section content from requirement_versions.content

After this migration:
- ACs exist ONLY in acceptance_criteria table
- Content field contains only a placeholder AC section header
- AC injection on read reconstructs the full content with current met status
"""
from typing import Sequence, Union
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision: str = '054'
down_revision: Union[str, None] = '053'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def extract_ac_categories(content: str) -> dict:
    """Extract category (subsection header) for each AC from content.

    Returns dict mapping (ordinal) -> category_name
    """
    if not content:
        return {}

    # Find Acceptance Criteria section with negative lookahead for subsections
    ac_section_pattern = r'##\s+Acceptance\s+Criteria\s*\n(.*?)(?=\n##(?!#)|\n#\s|\Z)'
    ac_match = re.search(ac_section_pattern, content, re.DOTALL | re.IGNORECASE)

    if not ac_match:
        return {}

    ac_section = ac_match.group(1)

    # Pattern to match subsection headers (### Header)
    subsection_pattern = r'^###\s+(.+)'
    # Pattern to match checkbox items: - [ ] text or - [x] text
    checkbox_pattern = r'^-\s*\[([ xX])\]\s*(.+?)$'

    categories = {}
    current_category = None
    ordinal = 1

    for line in ac_section.split('\n'):
        line_stripped = line.strip()

        # Check for subsection header (category)
        subsection_match = re.match(subsection_pattern, line_stripped)
        if subsection_match:
            current_category = subsection_match.group(1).strip()
            continue

        # Check for checkbox item
        checkbox_match = re.match(checkbox_pattern, line_stripped)
        if checkbox_match:
            criteria_text = checkbox_match.group(2).strip()

            # Skip placeholder text
            if criteria_text.startswith('[') and criteria_text.endswith(']'):
                continue
            if len(criteria_text) < 3:
                continue

            # Map ordinal to category
            categories[ordinal] = current_category  # May be None
            ordinal += 1

    return categories


def strip_ac_section_from_content(content: str) -> str:
    """Strip AC section content, leaving only placeholder header."""
    if not content:
        return content

    # Find Acceptance Criteria section with negative lookahead for subsections
    ac_section_pattern = r'(##\s+Acceptance\s+Criteria\s*\n)(.*?)(?=\n##(?!#)|\n#\s|\Z)'
    ac_match = re.search(ac_section_pattern, content, re.DOTALL | re.IGNORECASE)

    if not ac_match:
        return content

    ac_header = ac_match.group(1)
    section_start = ac_match.start()
    section_end = ac_match.end()

    # Replace section with just the header and a placeholder comment
    new_ac_section = ac_header + "\n<!-- AC content injected from acceptance_criteria table -->\n"

    return content[:section_start] + new_ac_section + content[section_end:]


def upgrade() -> None:
    """Backfill categories and strip AC content."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Step 1: Backfill categories on existing acceptance_criteria records
    # Get all versions with their content and ACs
    versions = session.execute(sa.text("""
        SELECT rv.id, rv.content
        FROM requirement_versions rv
        WHERE rv.content IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM acceptance_criteria ac
            WHERE ac.requirement_version_id = rv.id
        )
    """)).fetchall()

    categories_updated = 0

    for version_id, content in versions:
        if not content:
            continue

        # Extract category mapping from content
        category_map = extract_ac_categories(content)

        if not category_map:
            continue

        # Get ACs for this version ordered by ordinal
        acs = session.execute(sa.text("""
            SELECT id, ordinal FROM acceptance_criteria
            WHERE requirement_version_id = :version_id
            ORDER BY ordinal
        """), {'version_id': version_id}).fetchall()

        for ac_id, ordinal in acs:
            category = category_map.get(ordinal)
            if category:
                session.execute(sa.text("""
                    UPDATE acceptance_criteria
                    SET category = :category
                    WHERE id = :ac_id
                """), {'category': category, 'ac_id': ac_id})
                categories_updated += 1

    session.commit()
    print(f"CR-017 DRY Migration: Updated {categories_updated} AC records with categories")

    # Step 2: Strip AC content from all requirement_versions
    # Get all versions with content containing AC section
    all_versions = session.execute(sa.text("""
        SELECT id, content
        FROM requirement_versions
        WHERE content IS NOT NULL
        AND content ~* '##\\s+Acceptance\\s+Criteria'
    """)).fetchall()

    content_stripped = 0

    for version_id, content in all_versions:
        if not content:
            continue

        stripped = strip_ac_section_from_content(content)

        if stripped != content:
            session.execute(sa.text("""
                UPDATE requirement_versions
                SET content = :content
                WHERE id = :version_id
            """), {'content': stripped, 'version_id': version_id})
            content_stripped += 1

    session.commit()
    print(f"CR-017 DRY Migration: Stripped AC content from {content_stripped} versions")


def downgrade() -> None:
    """Cannot easily restore stripped content - would need to rebuild from AC table."""
    # This is a one-way migration. The original content is not preserved.
    # To restore, you would need to inject ACs back into content permanently.
    print("WARNING: Cannot restore stripped AC content. "
          "Content would need to be rebuilt from acceptance_criteria table.")
