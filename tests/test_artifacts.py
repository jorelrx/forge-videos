import pytest

from forge.api.ranges import parse_range, ByteRange, RangeNotSatisfiable


def test_range_invalid_size_raises():
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=0-", 0)


def test_artifact_preview_mime_safety():
    from forge.services.catalogo import PREVIEW_MIME
    # PREVIEW_MIME contém apenas tipos permitidos
    assert "text/markdown" in PREVIEW_MIME
    assert "image/png" in PREVIEW_MIME
    assert "audio/wav" in PREVIEW_MIME
    assert "video/mp4" in PREVIEW_MIME
    # Tipos não permitidos não estão presentes
    assert "application/exe" not in PREVIEW_MIME
