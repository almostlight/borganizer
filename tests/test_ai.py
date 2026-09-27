import pytest

from borganizer.ai import _resolution


def test_ai_response_is_strictly_validated():
    result = _resolution({"book": "The Final Empire", "author": "Brandon Sanderson", "series": "Mistborn", "series_number": 1, "confidence": 0.97})
    assert result.book == "The Final Empire"
    assert result.confidence == 0.97


def test_ai_response_rejects_filesystem_instead_of_metadata():
    with pytest.raises(ValueError):
        _resolution({"move": "/tmp/file", "confidence": 1.0})