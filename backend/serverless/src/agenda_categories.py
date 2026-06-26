"""Domain-managed agenda category inference for patient questions."""

from __future__ import annotations

import re

from domain_config import agenda_category_rules
from utils import clean_quote


AGENDA_CATEGORY_PRIORITY = {
    "supplement_drug_interaction": 0,
    "food_drug_interaction": 1,
    "drug_drug_interaction": 2,
    "treatment_duration": 3,
    "followup_visit": 4,
    "test_question": 5,
    "lifestyle": 6,
}


def infer_agenda_category(text: str, current_category: str = "other") -> str:
    """Return a specific agenda category when domain rules match the question text."""
    category = clean_quote(current_category or "other")
    if category and category != "other":
        return category

    normalized = re.sub(r"\s+", " ", clean_quote(text)).strip()
    if not normalized:
        return category or "other"

    matches = []
    for rule in agenda_category_rules():
        rule_category = clean_quote(rule.get("category") or "")
        groups = rule.get("all_of") or []
        if not rule_category or not isinstance(groups, list):
            continue
        if all(_matches_any_token(normalized, group) for group in groups if isinstance(group, list)):
            matches.append(rule_category)
    if matches:
        return sorted(matches, key=lambda item: AGENDA_CATEGORY_PRIORITY.get(item, 99))[0]
    return category or "other"


def _matches_any_token(text: str, tokens: list[str]) -> bool:
    return any(clean_quote(token) and clean_quote(token) in text for token in tokens)
