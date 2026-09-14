# RED: testes para ranges + artifacts falham conforme esperado
from forge.api.ranges import parse_range, ByteRange, RangeNotSatisfiable


def test_range_invalid_size_raises():
    # RED: ainda não implementa segurança de path/MIME completa
    assert False, "RED: range/artifact tests não finalizados"


def test_artifact_preview_mime_safety():
    # RED: rotas não verificam MIME nem bloqueiam path traversal
    assert False, "RED: preview MIME/security não ajustado"
