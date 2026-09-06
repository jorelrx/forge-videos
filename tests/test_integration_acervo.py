import pytest

from forge.infrastructure.config import Settings
from forge.services.acervo import Acervo


@pytest.mark.integration
def test_acervo_real_responde_e_devolve_caminho_citavel():
    """Exige o acervo no ar em FORGE_ACERVO_URL. Único teste que usa rede."""
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    acervo = Acervo(s.acervo_url, timeout=s.acervo_timeout)

    if not acervo.saude():
        pytest.skip(f"acervo fora do ar em {s.acervo_url}")

    passagens = acervo.buscar("livre-arbítrio e determinismo", top=3)

    assert passagens, "acervo no ar mas sem passagens; confira se há livros ingeridos"

    paths = [p.path for p in passagens]
    assert all(paths), f"passagem sem path canônico; paths recebidos: {paths}"

    titulos = [p.book_title for p in passagens]
    assert all(titulos), f"passagem sem book_title; titulos recebidos: {titulos}"
