from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz.fuzz import token_set_ratio

from .models import BookMetadata


@dataclass(frozen=True)
class MatchResult:
    kind: str
    method: str
    score: float


def normalize_text(value: str | None) -> str:
    value = (value or "").casefold().replace("&", " and ")
    value = re.sub(r"\b(unabridged|abridged|unrated|complete|dramatized)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def normalize_author(value: str | None) -> str:
    tokens = normalize_text(value).split()
    return " ".join(token for token in tokens if len(token) > 2)


def normalize_identifier(value: str | None) -> str | None:
    if not value:
        return None
    identifier = re.sub(r"[^0-9x]", "", value.casefold())
    return identifier or None


def title_key(meta: BookMetadata) -> str:
    return normalize_text(meta.title)


def author_key(meta: BookMetadata) -> str:
    return normalize_author(meta.author)


def _same_edition(left: BookMetadata, right: BookMetadata) -> bool:
    left_isbn = normalize_identifier(left.isbn)
    right_isbn = normalize_identifier(right.isbn)
    if left_isbn or right_isbn:
        return bool(left_isbn and right_isbn and left_isbn == right_isbn)

    for left_value, right_value in (
        (left.narrator, right.narrator),
        (left.publisher, right.publisher),
        (left.language, right.language),
    ):
        if left_value and right_value and normalize_text(left_value) != normalize_text(right_value):
            return False
    return True


def classify_match(left: BookMetadata, right: BookMetadata, *, duplicate: bool = False) -> MatchResult | None:
    if duplicate:
        return MatchResult("duplicate file", "sha256", 1.0)

    left_isbn = normalize_identifier(left.isbn)
    right_isbn = normalize_identifier(right.isbn)
    if left_isbn and right_isbn and left_isbn == right_isbn:
        method = "ISBN / exact identifier"
    elif title_key(left) and title_key(left) == title_key(right) and author_key(left) and author_key(left) == author_key(right):
        method = "normalized title + author"
    elif (
        normalize_text(left.series)
        and normalize_text(left.series) == normalize_text(right.series)
        and (
            (left.series_number is not None and left.series_number == right.series_number)
            or (
                left.series_position_label
                and normalize_text(left.series_position_label) == normalize_text(right.series_position_label)
            )
        )
    ):
        method = "series + series number"
    else:
        title_score = token_set_ratio(title_key(left), title_key(right)) / 100 if title_key(left) and title_key(right) else 0.0
        author_score = token_set_ratio(author_key(left), author_key(right)) / 100 if author_key(left) and author_key(right) else 0.0
        if title_score < 0.88 or (author_score and author_score < 0.75):
            return None
        method = "fuzzy matching"
        score = 0.7 * title_score + 0.3 * author_score if author_score else title_score
        return MatchResult("same edition" if _same_edition(left, right) else "different edition", method, score)

    return MatchResult("same edition" if _same_edition(left, right) else "different edition", method, 1.0)