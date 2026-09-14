from __future__ import annotations

# RED: rotas /api/services e /api/config/effective ainda não completas.
# Os testes abaixo falham de propósito para marcar o estado parcial.


def test_services_route_exists():
    from forge.api.routes.system import system_router
    # Stub existe, mas ainda não está incluído no app principal.
    assert system_router is not None
    # Falha esperada: rotas incompletas e não registradas no FastAPI.
    assert False, "RED — routes /api/services incompletas e não registradas no app"


def test_effective_config_redacts_keys():
    # RED: redaction de chaves ainda não implementada.
    assert False, "RED — /api/config/effective sem redaction de chaves"


def test_system_routes_return_structured_health():
    # RED: sem integração com StudioHealthService ainda.
    assert False, "RED — integração health/config ainda ausente"
