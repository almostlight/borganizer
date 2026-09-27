from borganizer.matching import classify_match
from borganizer.models import BookMetadata


def metadata(title, author=None, narrator=None, isbn=None):
    return BookMetadata(title=title, author=author, narrator=narrator, isbn=isbn)


def test_hobbit_variants_match_by_normalized_title_and_author():
    canonical = metadata("The Hobbit", "J. R. R. Tolkien")
    assert classify_match(metadata("Tolkien - The Hobbit"), canonical) is not None
    assert classify_match(metadata("The Hobbit", "Tolkien"), canonical).kind == "same edition"


def test_unabridged_filename_matches_by_fuzzy_title():
    result = classify_match(metadata("The_Hobbit_Unabridged"), metadata("The Hobbit", "Tolkien"))
    assert result is not None
    assert result.method == "fuzzy matching"


def test_narrator_difference_is_a_different_edition():
    result = classify_match(
        metadata("The Hobbit", "Tolkien", narrator="Narrator A"),
        metadata("The Hobbit", "Tolkien", narrator="Narrator B"),
    )
    assert result.kind == "different edition"


def test_same_isbn_is_same_edition():
    result = classify_match(metadata("The Hobbit", isbn="9780261102217"), metadata("Hobbit", isbn="978-0-261-10221-7"))
    assert result.method == "ISBN / exact identifier"
    assert result.kind == "same edition"