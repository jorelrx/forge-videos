# RED: testes para ranges + artifacts falham conforme esperado
from forge.api.ranges import parse_range, ByteRange, RangeNotSatisfiable
from forge.services.catalogo import PREVIEW_MIME


def test_range_invalid_size_raises():
    # RangeNotSatisfiable quando size <= 0
    try:
        parse_range("bytes=0-", 0)
        assert False, "deveria levantar RangeNotSatisfiable"
    except RangeNotSatisfiable:
        pass


def test_artifact_preview_mime_safety():
    # PREVIEW_MIME contém apenas tipos permitidos
    assert "text/markdown" in PREVIEW_MIME
    assert "image/png" in PREVIEW_MIME
    assert "audio/wav" in PREVIEW_MIME
    # Tipos não permitidos não estão presentes
    assert "application/exe" not in PREVIEW_MIME
