import os
import random
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from forge.services.thumbnail import (
    ALTURA,
    BYTES_MAXIMO,
    LARGURA,
    compor_thumbnail,
)

FONTE = Path(r"C:\Windows\Fonts\georgiab.ttf")
precisa_fonte = pytest.mark.skipif(not FONTE.exists(), reason="TTF ausente")


def _base(caminho: Path, tamanho=(1024, 576)) -> Path:
    img = Image.new("RGB", tamanho, (30, 60, 110))
    # Faixa clara na metade direita: ajuda a ver se o corte não distorce.
    img.paste((220, 200, 120), (tamanho[0] // 2, 0, tamanho[0], tamanho[1]))
    img.save(caminho)
    return caminho


def test_saida_e_jpeg_1280x720(tmp_path):
    base = _base(tmp_path / "base.png")
    saida = tmp_path / "t.jpg"
    info = compor_thumbnail(base, "", saida, fonte=None)
    with Image.open(saida) as img:
        assert img.format == "JPEG"
        assert img.size == (LARGURA, ALTURA) == (1280, 720)
    assert (info.largura, info.altura) == (1280, 720)


@pytest.mark.parametrize("tamanho", [(576, 1024), (2000, 700), (1280, 720)])
def test_qualquer_proporcao_vira_1280x720(tmp_path, tamanho):
    base = _base(tmp_path / "base.png", tamanho)
    saida = tmp_path / "t.jpg"
    compor_thumbnail(base, "", saida, fonte=None)
    with Image.open(saida) as img:
        assert img.size == (1280, 720)


def test_corte_ao_centro_sem_distorcer(tmp_path):
    # Base em retrato: topo vermelho, meio verde, fundo azul. O corte ao centro
    # deve ficar só com o verde; distorção deixaria vermelho/azul à vista.
    img = Image.new("RGB", (400, 1200))
    img.paste((255, 0, 0), (0, 0, 400, 400))
    img.paste((0, 255, 0), (0, 400, 400, 800))
    img.paste((0, 0, 255), (0, 800, 400, 1200))
    base = tmp_path / "retrato.png"
    img.save(base)
    saida = tmp_path / "t.jpg"
    compor_thumbnail(base, "", saida, fonte=None)
    with Image.open(saida) as out:
        r, g, b = out.getpixel((1100, 360))  # longe do gradiente à esquerda
        assert g > 200 and r < 60 and b < 60
        r, g, b = out.getpixel((1100, 5))
        assert g > 200 and r < 60 and b < 60


def test_arquivo_ate_2mb_mesmo_com_ruido(tmp_path):
    rng = random.Random(7)
    ruido = Image.frombytes("RGB", (1024, 576), rng.randbytes(1024 * 576 * 3))
    base = tmp_path / "ruido.png"
    ruido.save(base)
    saida = tmp_path / "t.jpg"
    info = compor_thumbnail(base, "", saida, fonte=None)
    assert os.path.getsize(saida) <= BYTES_MAXIMO
    assert info.bytes <= BYTES_MAXIMO


def test_bytes_bate_com_o_arquivo(tmp_path):
    base = _base(tmp_path / "base.png")
    saida = tmp_path / "t.jpg"
    info = compor_thumbnail(base, "", saida, fonte=None)
    assert info.bytes == os.path.getsize(saida)


@precisa_fonte
def test_com_fonte_e_texto_desenha(tmp_path):
    base = _base(tmp_path / "base.png")
    sem = tmp_path / "sem.jpg"
    com = tmp_path / "com.jpg"
    compor_thumbnail(base, "", sem, fonte=FONTE)
    info = compor_thumbnail(base, "O que o silêncio ensina", com, fonte=FONTE)
    assert info.com_texto is True
    with Image.open(sem) as a, Image.open(com) as b:
        assert ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()


def test_sem_fonte_sai_sem_texto(tmp_path):
    base = _base(tmp_path / "base.png")
    info = compor_thumbnail(base, "Texto", tmp_path / "t.jpg", fonte=None)
    assert info.com_texto is False


def test_fonte_inexistente_sai_sem_texto(tmp_path):
    base = _base(tmp_path / "base.png")
    info = compor_thumbnail(
        base, "Texto", tmp_path / "t.jpg", fonte=tmp_path / "nao-existe.ttf",
    )
    assert info.com_texto is False
    assert (tmp_path / "t.jpg").exists()


def test_fonte_ilegivel_sai_sem_texto(tmp_path):
    base = _base(tmp_path / "base.png")
    falsa = tmp_path / "falsa.ttf"
    falsa.write_bytes(b"isto nao e uma fonte")
    info = compor_thumbnail(base, "Texto", tmp_path / "t.jpg", fonte=falsa)
    assert info.com_texto is False


@precisa_fonte
def test_texto_vazio_sai_sem_texto(tmp_path):
    base = _base(tmp_path / "base.png")
    for vazio in ("", "   ", "\n"):
        info = compor_thumbnail(base, vazio, tmp_path / "t.jpg", fonte=FONTE)
        assert info.com_texto is False


@precisa_fonte
def test_quatro_palavras_cabem_na_area_de_texto(tmp_path):
    # Base preta: tudo que não for escuro, fora do gradiente, é texto. A área
    # de texto são os ~55% da esquerda; à direita nada pode ser desenhado.
    base = tmp_path / "preta.png"
    Image.new("RGB", (1024, 576), (0, 0, 0)).save(base)
    saida = tmp_path / "t.jpg"
    info = compor_thumbnail(base, "Você não é seu pensamento", saida, fonte=FONTE)
    assert info.com_texto is True
    with Image.open(saida) as img:
        cinza = img.convert("L").point(lambda v: 255 if v > 90 else 0)
        x0, y0, x1, y1 = cinza.getbbox()
        assert x1 <= LARGURA * 0.60
        assert x0 >= 0 and y0 >= 0 and y1 <= ALTURA
        # Duas linhas no máximo: o texto ocupa no máximo ~60% da altura.
        assert (y1 - y0) <= ALTURA * 0.62
