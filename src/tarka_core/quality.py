"""Content quality validation and scoring logic."""
from typing import Optional
from .models import RequirementType, QualityScore


# Length thresholds by requirement type (in characters)
LENGTH_THRESHOLDS = {
    RequirementType.EPIC: {
        "target": 3000,
        "warning": 5000,
        "hard_max": 8000,
    },
    RequirementType.COMPONENT: {
        "target": 4000,
        "warning": 6000,
        "hard_max": 10000,
    },
    RequirementType.FEATURE: {
        "target": 5000,
        "warning": 7000,
        "hard_max": 12000,
    },
    RequirementType.REQUIREMENT: {
        "target": 2000,
        "warning": 3000,
        "hard_max": 5000,
    },
}


def calculate_quality_score(
    content_length: int,
    requirement_type: RequirementType
) -> QualityScore:
    """
    Calculate quality score based on content length and requirement type.

    Args:
        content_length: Length of markdown content in characters
        requirement_type: Type of requirement

    Returns:
        QualityScore enum value (OK, NEEDS_REVIEW, or LOW_QUALITY)
    """
    thresholds = LENGTH_THRESHOLDS[requirement_type]

    if content_length >= thresholds["hard_max"]:
        return QualityScore.LOW_QUALITY
    elif content_length >= thresholds["warning"]:
        return QualityScore.NEEDS_REVIEW
    else:
        return QualityScore.OK


def is_content_length_valid_for_approval(
    content_length: int,
    requirement_type: RequirementType
) -> bool:
    """
    Check if content length allows approval/review status.

    Args:
        content_length: Length of markdown content in characters
        requirement_type: Type of requirement

    Returns:
        True if length is acceptable, False if it exceeds hard max
    """
    thresholds = LENGTH_THRESHOLDS[requirement_type]
    return content_length < thresholds["hard_max"]


def get_length_validation_error(
    content_length: int,
    requirement_type: RequirementType
) -> Optional[str]:
    """
    Get validation error message if content exceeds hard max.

    Args:
        content_length: Length of markdown content in characters
        requirement_type: Type of requirement

    Returns:
        Error message string if invalid, None if valid
    """
    thresholds = LENGTH_THRESHOLDS[requirement_type]

    if content_length >= thresholds["hard_max"]:
        return (
            f"Content length ({content_length} characters) exceeds maximum allowed "
            f"for {requirement_type.value} ({thresholds['hard_max']} characters). "
            f"Requirements exceeding the hard maximum cannot be approved and must be "
            f"decomposed into smaller, more focused items. "
            f"Target length: {thresholds['target']} characters."
        )
    return None
