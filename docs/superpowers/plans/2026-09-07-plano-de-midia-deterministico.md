# Plano de mídia determinístico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garantir que o plano de mídia cubra o roteiro inteiro, palavra por palavra, tirando o fatiamento das mãos do modelo.

**Architecture:** O fatiamento vira código: um módulo puro corta cada seção em blocos de 1 a 3 frases, descartando a rubrica de cena e a ênfase markdown, sem nunca reescrever uma palavra. O LLM passa a ser chamado uma vez por seção e só para propor prompts de imagem, recebendo os blocos já prontos e a rubrica daquela seção como semente visual. Uma trava de cobertura recusa o plano que não contenha todas as palavras narráveis do roteiro.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, langchain-core, pytest, structlog.

**Spec:** [docs/superpowers/specs/2026-09-06-video-pipeline-design.md](../specs/2026-09-06-video-pipeline-design.md) — sub-projeto S3, decisão D12 e a seção "Revisão de S3 — o fatiamento sai do LLM".

## Global Constraints

- Nomes de domínio, de estado e mensagens de log em português; identificadores de código misturam português e inglês. Casar com o arquivo ao redor.
- Log estruturado com `structlog`: `get_logger(__name__)`, campos `chave=valor`, nunca f-string dentro da chamada de log.
- Nenhum teste toca a rede, a GPU ou um binário externo. Modelo é a fixture `scripted`.
- Nenhuma palavra do roteiro pode ser perdida ou reescrita pelo fatiamento. É a propriedade central deste plano e todo teste existe para prová-la.
- Sem dependências novas. Nada de `nltk`, `spacy` ou modelo de sentença — o corte é regex sobre pontuação.
- `docs/superpowers/` está no `.gitignore`.
- Mensagens de commit em inglês, prefixo `feat:`/`fix:`/`refactor:`/`test:`, corpo terminando em `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Por que, com números

`planejar_midia` foi exercitado contra o roteiro real de `output/runs/20260906-183127-*` (1079 palavras, 9 seções). Produziu **3 blocos, 85 palavras, só do Hook** — 8% do roteiro — e listou beats apontando para `b_014` … `b_078`, blocos que nunca escreveu. O descarte de órfãos limpou a inconsistência, e o plano resultante era coerente e quase vazio. Nada detectaria isso adiante: o `forge video` narraria 36 segundos de um roteiro de sete minutos e marcaria tudo `ok` no manifesto.

Forma real do texto que o fatiador recebe, verificada no artefato `03-write-r2.md`:

```markdown
## Hook

(Cena: Um carro acelerando numa estrada reta. O motorista olha para o painel e depois para o volante.)

Eu sei exatamente qual é a posição de cada peça no meu motor agora. Eu sei a velocidade do vento, da temperatura e onde vai dar o próximo obstáculo. Se eu fosse um computador, eu já teríamos calculado o ângulo exato da minha mão antes mesmo de ela mexer. Mas quando eu sinto vontade de virar a esquerda, não é porque uma engrenagem girou. É algo que acontece *dentro* do tempo.
```

Três coisas saltam daí: a rubrica entre parênteses não é narração, a ênfase markdown não pode ir ao TTS, e o corpo é prosa comum separada por ponto final.

---

### Task 1: Fatiador determinístico

**Files:**
- Create: `src/forge/narracao/fatiar.py`
- Create: `tests/narracao/test_fatiar.py`

**Interfaces:**
- Consumes: nada além da stdlib.
- Produces, em `forge.narracao.fatiar`:
  - `RUBRICA_RE: re.Pattern` — linha inteiramente entre parênteses
  - `extrair_rubrica(conteudo: str) -> str` — o texto da rubrica sem os parênteses, ou `""`
  - `texto_narravel(conteudo: str) -> str` — o conteúdo sem rubrica e sem ênfase markdown
  - `dividir_frases(texto: str) -> list[str]`
  - `fatiar(conteudo: str, *, max_frases: int = 3, alvo_palavras: int = 35) -> list[str]` — os blocos de texto de UMA seção, na ordem

- [ ] **Step 1: Escrever os testes**

Criar `tests/narracao/test_fatiar.py`:

```python
from forge.narracao.fatiar import (
    dividir_frases,
    extrair_rubrica,
    fatiar,
    texto_narravel,
)

# Trecho literal de output/runs/20260906-183127-*/03-write-r2.md, seção Hook.
HOOK = """(Cena: Um carro acelerando numa estrada reta. O motorista olha para o painel e depois para o volante.)

Eu sei exatamente qual é a posição de cada peça no meu motor agora. Eu sei a velocidade do vento, da temperatura e onde vai dar o próximo obstáculo. Se eu fosse um computador, eu já teríamos calculado o ângulo exato da minha mão antes mesmo de ela mexer. Mas quando eu sinto vontade de virar a esquerda, não é porque uma engrenagem girou. É algo que acontece *dentro* do tempo. A ciência diz que tudo é previsível. O meu corpo diz que eu escolhi. Se a ciência está certa, por que eu me sinto livre?"""


def test_rubrica_de_cena_nao_e_narracao():
    """A rubrica descreve a imagem, não o que a voz diz. Narrá-la seria absurdo."""
    assert "Cena:" not in texto_narravel(HOOK)
    assert texto_narravel(HOOK).startswith("Eu sei exatamente")


def test_rubrica_e_recuperavel_para_semente_visual():
    rubrica = extrair_rubrica(HOOK)

    assert rubrica.startswith("Cena: Um carro acelerando")
    assert not rubrica.endswith(")")


def test_parentese_no_meio_da_frase_nao_e_rubrica():
    """`RUBRICA_RE` usa DOTALL: sem as âncoras de linha ele engoliria daqui até
    o último parêntese do texto, apagando narração."""
    conteudo = (
        "(Cena: um carro.)\n\n"
        "Hume (que era escocês) discordou. Depois calou.\n\n"
        "Outra frase (com aparte) aqui."
    )

    narravel = texto_narravel(conteudo)

    assert "Cena:" not in narravel
    assert "que era escocês" in narravel
    assert "com aparte" in narravel
    assert narravel.startswith("Hume")


def test_secao_sem_rubrica_nao_perde_texto():
    conteudo = "Primeira frase. Segunda frase."

    assert extrair_rubrica(conteudo) == ""
    assert texto_narravel(conteudo) == conteudo


def test_enfase_markdown_sai_mas_a_palavra_fica():
    """O TTS não deve receber asterisco; a palavra em si é narração."""
    assert texto_narravel("É algo que acontece *dentro* do tempo.") == (
        "É algo que acontece dentro do tempo."
    )
    assert texto_narravel("Isso é **muito** claro.") == "Isso é muito claro."
    assert texto_narravel("Isso é _sutil_ demais.") == "Isso é sutil demais."


def test_divide_por_pontuacao_final():
    frases = dividir_frases("Uma. Duas! Três? Quatro.")

    assert frases == ["Uma.", "Duas!", "Três?", "Quatro."]


def test_abreviacao_nao_quebra_a_frase():
    """Um ponto depois de Sr. não termina frase; quebrar ali corta a narração no meio."""
    frases = dividir_frases("O Sr. Hume discordou. Depois calou.")

    assert frases == ["O Sr. Hume discordou.", "Depois calou."]


def test_reticencias_nao_viram_tres_frases():
    assert dividir_frases("Ele hesitou... e então falou.") == [
        "Ele hesitou... e então falou."
    ]


def test_nenhuma_palavra_se_perde():
    """A propriedade central: fatiar é cortar, nunca editar."""
    blocos = fatiar(HOOK)
    esperado = texto_narravel(HOOK).split()

    assert " ".join(blocos).split() == esperado


def test_blocos_respeitam_o_teto_de_frases():
    blocos = fatiar(HOOK, max_frases=3)

    for bloco in blocos:
        assert 1 <= len(dividir_frases(bloco)) <= 3


def test_frase_longa_sozinha_vira_um_bloco():
    """Frase que já passa do alvo de palavras não ganha companhia."""
    longa = " ".join(["palavra"] * 60) + "."
    blocos = fatiar(longa + " Curta.", alvo_palavras=35)

    assert blocos[0] == longa
    assert blocos[1] == "Curta."


def test_secao_vazia_nao_gera_bloco():
    assert fatiar("(Cena: nada acontece.)\n\n") == []
    assert fatiar("   ") == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/narracao/test_fatiar.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'forge.narracao.fatiar'`

- [ ] **Step 3: Implementar**

Criar `src/forge/narracao/fatiar.py`:

```python
"""Corta o roteiro em blocos de narração — sem LLM, por construção.

Fatiar é operação determinística: nenhuma palavra pode ser perdida ou reescrita.
Um modelo faz isso com risco de truncar, pular ou reescrever, e foi exatamente o
que aconteceu na primeira versão: pediu-se a um 9B que fatiasse 1079 palavras e
ele devolveu 85, todas do Hook, mais beats apontando para blocos que nunca
escreveu. Aqui a cobertura é garantida porque o código só corta.
"""

from __future__ import annotations

import re

# Linha inteiramente entre parênteses: a rubrica de cena que o escritor põe no
# começo de cada seção. Descreve a imagem, não o que a voz diz.
RUBRICA_RE = re.compile(r"^\s*\((.+?)\)\s*$", re.MULTILINE | re.DOTALL)

# Ênfase markdown. O asterisco não pode chegar ao TTS; a palavra sim.
_ENFASE_RE = re.compile(r"(\*\*|\*|_)(.+?)\1", re.DOTALL)

# Abreviações que terminam em ponto sem terminar a frase. Cortar depois delas
# partiria a narração no meio de uma oração.
_ABREVIACOES = ("Sr.", "Sra.", "Srta.", "Dr.", "Dra.", "Prof.", "St.", "etc.")
_MARCA = "\x00"

# Fim de frase: pontuação final (com reticências tratadas como uma só) seguida
# de espaço e de algo que começa frase nova.
_FIM_FRASE_RE = re.compile(r"(?<=[.!?…])(?<!\.\.)\s+(?=[^\s])")


def extrair_rubrica(conteudo: str) -> str:
    """A rubrica de cena da seção, sem os parênteses. Vazio se não houver.

    Não é narração, mas é uma descrição visual escrita pelo autor — serve de
    semente para os prompts de imagem daquela seção.
    """
    achado = RUBRICA_RE.search(conteudo)
    return achado.group(1).strip() if achado else ""


def texto_narravel(conteudo: str) -> str:
    """O que a voz de fato diz: sem rubrica, sem ênfase markdown."""
    sem_rubrica = RUBRICA_RE.sub("", conteudo)
    sem_enfase = _ENFASE_RE.sub(r"\2", sem_rubrica)
    return " ".join(sem_enfase.split())


def dividir_frases(texto: str) -> list[str]:
    protegido = texto
    for i, abrev in enumerate(_ABREVIACOES):
        protegido = protegido.replace(abrev, f"{_MARCA}{i}{_MARCA}")

    frases = [f.strip() for f in _FIM_FRASE_RE.split(protegido) if f.strip()]

    restauradas = []
    for frase in frases:
        for i, abrev in enumerate(_ABREVIACOES):
            frase = frase.replace(f"{_MARCA}{i}{_MARCA}", abrev)
        restauradas.append(frase)
    return restauradas


def fatiar(
    conteudo: str, *, max_frases: int = 3, alvo_palavras: int = 35
) -> list[str]:
    """Blocos de 1 a `max_frases` frases, mirando `alvo_palavras` por bloco.

    O alvo é teto flexível, não corte: uma frase que sozinha já o excede vira um
    bloco só dela, porque quebrar no meio de uma frase é o único jeito de o TTS
    soar errado sem que ninguém perceba no texto.
    """
    frases = dividir_frases(texto_narravel(conteudo))
    blocos: list[str] = []
    atual: list[str] = []
    palavras = 0

    for frase in frases:
        n = len(frase.split())
        cheio = len(atual) >= max_frases or (atual and palavras + n > alvo_palavras)
        if cheio:
            blocos.append(" ".join(atual))
            atual, palavras = [], 0
        atual.append(frase)
        palavras += n

    if atual:
        blocos.append(" ".join(atual))
    return blocos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/narracao/test_fatiar.py -v`
Expected: PASS, 11 testes

- [ ] **Step 5: Provar a cobertura contra o roteiro real inteiro**

O teste `test_nenhuma_palavra_se_perde` cobre uma seção. Rodar também contra as nove, uma vez, à mão:

```bash
uv run python -c "
import re
from pathlib import Path
from forge.narracao.fatiar import fatiar, texto_narravel
p = sorted(Path('output/runs').glob('20260906-183127-*'))[0] / '03-write-r2.md'
t = p.read_text(encoding='utf-8')
total_esperado = total_obtido = 0
for s in re.split(r'^## ', t, flags=re.M)[1:]:
    nome, corpo = s.split(chr(10), 1)
    esperado = texto_narravel(corpo).split()
    obtido = ' '.join(fatiar(corpo)).split()
    assert obtido == esperado, nome
    total_esperado += len(esperado); total_obtido += len(obtido)
    print(f'{nome.strip():12} {len(esperado):5} palavras  {len(fatiar(corpo)):3} blocos')
print('TOTAL', total_esperado, '==', total_obtido)
"
```

Expected: cada seção bate exatamente, total ~1079 palavras. Registrar a saída no relatório. Se alguma seção divergir, o fatiador está errado — corrigir antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: slice narration blocks in code, not in the model

Slicing is deterministic work: no word may be lost or rewritten. Asking a 9B to
do it produced 85 words out of 1079, all from the first section, plus beats
pointing at blocks it never wrote. This module only cuts, so coverage holds by
construction. Scene directions and markdown emphasis are stripped: neither
belongs in a TTS stream.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Beats por seção

**Files:**
- Create: `src/forge/prompts/beats.md`
- Delete: `src/forge/prompts/midia.md`
- Modify: `src/forge/agents/midia.py`
- Modify: `src/forge/domain/midia.py`
- Modify: `tests/agents/test_midia.py`

**Interfaces:**
- Consumes: `fatiar`, `extrair_rubrica` (Task 1); `BlocoNarracao`, `Beat` (`domain/midia.py`).
- Produces:
  - `class BeatsDaSecao(BaseModel)` com `beats: list[BeatProposto]` em `domain/midia.py`, e `class BeatProposto(BaseModel)` com `bloco_id: str` e `prompt: str`
  - `propor_beats(model, secao: str, rubrica: str, blocos: list[BlocoNarracao], *, alvo_segundos: int) -> list[Beat]` em `agents/midia.py` — ids dos beats ainda provisórios, renumerados depois

- [ ] **Step 1: Escrever os testes**

Substituir o conteúdo de `tests/agents/test_midia.py` (o antigo testava o fatiamento por LLM, que deixou de existir) por:

```python
import pytest

from forge.agents.midia import propor_beats
from forge.domain.midia import BeatProposto, BeatsDaSecao, BlocoNarracao


def _blocos():
    return [
        BlocoNarracao(id="b001", secao="Hook", texto="Primeira frase do gancho."),
        BlocoNarracao(id="b002", secao="Hook", texto="Segunda frase do gancho."),
    ]


def test_beats_apontam_para_blocos_da_secao(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="a hand on a steering wheel"),
        BeatProposto(bloco_id="b002", prompt="a road stretching to the horizon"),
    ])])

    beats = propor_beats(model, "Hook", "Cena: um carro", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001", "b002"]
    assert beats[0].prompt == "a hand on a steering wheel"


def test_beat_para_bloco_de_fora_da_secao_e_descartado(scripted):
    """O modelo só recebeu os blocos desta seção; citar outro é invenção."""
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="ok"),
        BeatProposto(bloco_id="b999", prompt="inventado"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001"]


def test_secao_sem_beat_proposto_ganha_um_de_fallback(scripted):
    """Uma seção sem imagem deixaria a tela congelada por minutos."""
    model = scripted(structured=[BeatsDaSecao(beats=[])])

    beats = propor_beats(model, "Hook", "Cena: um carro na estrada", _blocos(),
                         alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].bloco_id == "b001"
    assert "carro" in beats[0].prompt


def test_fallback_sem_rubrica_usa_o_nome_da_secao(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[])])

    beats = propor_beats(model, "Problema", "", _blocos(), alvo_segundos=15)

    assert len(beats) == 1
    assert "Problema" in beats[0].prompt


def test_prompt_vazio_nao_vira_beat(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="   "),
        BeatProposto(bloco_id="b002", prompt="uma estrada"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.prompt for b in beats] == ["uma estrada"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_midia.py -v`
Expected: FAIL com `ImportError: cannot import name 'propor_beats'`

- [ ] **Step 3: Modelos do que o LLM devolve**

Em `src/forge/domain/midia.py`, acrescentar:

```python
class BeatProposto(BaseModel):
    """O que o modelo devolve por seção: em qual bloco a imagem entra e o quê.

    `id` não aparece aqui de propósito — ids são nossos, atribuídos depois.
    """

    bloco_id: str
    prompt: str


class BeatsDaSecao(BaseModel):
    beats: list[BeatProposto] = Field(default_factory=list)
```

- [ ] **Step 4: Prompt dos beats**

Criar `src/forge/prompts/beats.md`:

```markdown
Você escolhe as imagens de um trecho de vídeo narrado.

Seção: {secao}
Direção de cena escrita pelo autor: {rubrica}

A narração já está cortada em blocos. Cada bloco tem um id:

{blocos}

Proponha cerca de {quantidade} imagens para esta seção — uma a cada
{alvo_segundos} segundos de narração, aproximadamente. Cada imagem indica o id
do bloco em que ela entra na tela e traz o prompt de geração.

Regras do prompt de imagem:

- em inglês, concreto e visual: cena, luz, composição, atmosfera;
- sem texto na imagem, sem rosto de pessoa real, sem logotipo;
- nada abstrato demais para desenhar — "a ideia de liberdade" não é imagem,
  "a bird leaving an open cage against a grey sky" é;
- vertical, pensado para tela de celular.

Use apenas ids que aparecem na lista acima. Não repita o mesmo bloco duas vezes.
```

- [ ] **Step 5: Implementar `propor_beats`**

Em `src/forge/agents/midia.py`, acrescentar (e importar `BeatProposto`, `BeatsDaSecao`):

```python
# ~2,5 palavras por segundo é a cadência medida do higgs nesta voz. Serve para
# estimar quantas imagens uma seção comporta, não para cronometrar nada: a
# duração real sai das métricas do TTS, no manifesto.
PALAVRAS_POR_SEGUNDO = 2.5


def propor_beats(
    model,
    secao: str,
    rubrica: str,
    blocos: list[BlocoNarracao],
    *,
    alvo_segundos: int,
) -> list[Beat]:
    if not blocos:
        return []

    palavras = sum(len(b.texto.split()) for b in blocos)
    quantidade = max(1, round(palavras / PALAVRAS_POR_SEGUNDO / alvo_segundos))

    prompt = load_prompt("beats").format(
        secao=secao,
        rubrica=rubrica or "(nenhuma)",
        blocos="\n".join(f"[{b.id}] {b.texto}" for b in blocos),
        quantidade=quantidade,
        alvo_segundos=alvo_segundos,
    )
    proposta = model.with_structured_output(BeatsDaSecao).invoke(
        [HumanMessage(content=prompt)]
    )

    validos = {b.id for b in blocos}
    beats: list[Beat] = []
    for p in proposta.beats:
        if p.bloco_id not in validos:
            logger.warning("Beat fora da seção descartado", secao=secao,
                           bloco_id=p.bloco_id)
            continue
        if not p.prompt.strip():
            logger.warning("Beat sem prompt descartado", secao=secao,
                           bloco_id=p.bloco_id)
            continue
        beats.append(Beat(id="", bloco_id=p.bloco_id, prompt=p.prompt.strip()))

    if not beats:
        # Seção sem imagem deixaria a tela congelada por minutos. A rubrica do
        # autor é a melhor descrição visual disponível sem gastar outra chamada.
        semente = rubrica or f"{secao} — cena ilustrativa"
        logger.warning("Seção sem beat; usando a rubrica", secao=secao)
        beats.append(Beat(id="", bloco_id=blocos[0].id, prompt=semente))

    logger.info("Beats da seção", secao=secao, propostos=len(proposta.beats),
                mantidos=len(beats))
    return beats
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/agents/test_midia.py -v`
Expected: PASS, 5 testes

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: ask the model for image beats one section at a time

The model no longer sees the whole script, only one section's blocks and the
author's own scene direction. It answers with block ids that must already
exist, so a beat it invents is dropped rather than anchored somewhere arbitrary.
A section that yields no beat falls back to the scene direction, because a
section with no image freezes the screen for minutes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `planejar_midia` costura, com trava de cobertura

**Files:**
- Modify: `src/forge/agents/midia.py`
- Modify: `tests/agents/test_midia.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `fatiar`, `extrair_rubrica` (Task 1); `propor_beats` (Task 2).
- Produces:
  - `class CoberturaInsuficiente(RuntimeError)` em `agents/midia.py`
  - `planejar_midia(model, roteiro: Roteiro, *, alvo_segundos: int = 15) -> PlanoMidia` — mesma assinatura de antes, comportamento novo
  - `_normalizar` deixa de existir: os ids passam a ser atribuídos durante a costura, e não há mais id de modelo para remapear

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/agents/test_midia.py`:

```python
def _roteiro_de_duas_secoes():
    from forge.domain.models import Roteiro, Secao

    return Roteiro(
        tema="livre-arbítrio",
        tese="a vontade é sentida, não observada",
        secoes=[
            Secao(nome="Hook", conteudo=(
                "(Cena: um carro na estrada.)\n\n"
                "Primeira frase do gancho. Segunda frase do gancho."
            )),
            Secao(nome="Problema", conteudo="O problema não é físico. É linguístico."),
        ],
    )


def test_plano_cobre_todas_as_secoes(scripted):
    from forge.agents.midia import planejar_midia

    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, _roteiro_de_duas_secoes())

    assert {b.secao for b in plano.blocos} == {"Hook", "Problema"}
    assert [b.id for b in plano.blocos] == ["b001", "b002"]
    assert [i.id for i in plano.beats] == ["i001", "i002"]


def test_nenhuma_palavra_do_roteiro_se_perde_no_plano(scripted):
    """A trava do plano inteiro: o que a voz diz tem de ser o roteiro inteiro."""
    from forge.agents.midia import planejar_midia
    from forge.narracao.fatiar import texto_narravel

    roteiro = _roteiro_de_duas_secoes()
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, roteiro)

    esperado = " ".join(texto_narravel(s.conteudo) for s in roteiro.secoes).split()
    assert " ".join(b.texto for b in plano.blocos).split() == esperado


def test_rubrica_nunca_entra_na_narracao(scripted):
    from forge.agents.midia import planejar_midia

    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, _roteiro_de_duas_secoes())

    assert all("Cena:" not in b.texto for b in plano.blocos)


def test_cobertura_insuficiente_estoura(scripted, monkeypatch):
    """Se um dia o fatiador regredir, o plano falha alto em vez de narrar 8%.

    É a lição do plano gerado por LLM: 85 palavras de 1079, todos os itens do
    manifesto marcados `ok`, e ninguém percebendo.
    """
    import forge.agents.midia as midia_mod
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia

    monkeypatch.setattr(midia_mod, "fatiar", lambda conteudo, **kw: ["só isto"])
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, _roteiro_de_duas_secoes())


def test_secao_so_com_rubrica_nao_gera_bloco_nem_chamada(scripted):
    from forge.agents.midia import planejar_midia
    from forge.domain.models import Roteiro, Secao

    roteiro = Roteiro(tema="t", tese="t", secoes=[
        Secao(nome="Hook", conteudo="(Cena: nada é dito.)"),
        Secao(nome="Problema", conteudo="Uma frase."),
    ])
    # Uma única resposta na fila: se o agente chamar o modelo para a seção sem
    # texto, o modelo falso estoura.
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a scale")]),
    ])

    plano = planejar_midia(model, roteiro)

    assert [b.secao for b in plano.blocos] == ["Problema"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agents/test_midia.py -v`
Expected: FAIL — `CoberturaInsuficiente` não existe e `planejar_midia` ainda usa o desenho antigo

- [ ] **Step 3: Reescrever `planejar_midia`**

Em `src/forge/agents/midia.py`, substituir `planejar_midia`, `_fmt_roteiro` e `_normalizar` por:

```python
class CoberturaInsuficiente(RuntimeError):
    """Os blocos não reproduzem o roteiro palavra por palavra.

    Existe por causa de um caso real: a versão anterior pedia o fatiamento ao
    LLM e recebeu 85 palavras de um roteiro de 1079, todas da primeira seção. O
    plano era coerente, o manifesto marcaria tudo `ok`, e o vídeo teria 36
    segundos de narração. Falhar alto aqui é a única defesa.
    """


def planejar_midia(model, roteiro: Roteiro, *, alvo_segundos: int = 15) -> PlanoMidia:
    blocos: list[BlocoNarracao] = []
    beats: list[Beat] = []

    for secao in roteiro.secoes:
        textos = fatiar(secao.conteudo)
        if not textos:
            # Seção só com rubrica não tem narração; não gasta chamada.
            logger.info("Seção sem texto narrável", secao=secao.nome)
            continue

        da_secao = [
            BlocoNarracao(id=f"b{len(blocos) + i + 1:03d}", secao=secao.nome, texto=t)
            for i, t in enumerate(textos)
        ]
        blocos.extend(da_secao)

        propostos = propor_beats(
            model,
            secao.nome,
            extrair_rubrica(secao.conteudo),
            da_secao,
            alvo_segundos=alvo_segundos,
        )
        for beat in propostos:
            beats.append(
                Beat(id=f"i{len(beats) + 1:03d}", bloco_id=beat.bloco_id,
                     prompt=beat.prompt)
            )

    _conferir_cobertura(roteiro, blocos)
    logger.info("Plano de mídia pronto", blocos=len(blocos), beats=len(beats),
                palavras=sum(len(b.texto.split()) for b in blocos))
    return PlanoMidia(blocos=blocos, beats=beats)


def _conferir_cobertura(roteiro: Roteiro, blocos: list[BlocoNarracao]) -> None:
    esperado = " ".join(texto_narravel(s.conteudo) for s in roteiro.secoes).split()
    obtido = " ".join(b.texto for b in blocos).split()
    if obtido != esperado:
        raise CoberturaInsuficiente(
            f"blocos cobrem {len(obtido)} palavras de {len(esperado)} do roteiro"
        )
```

Ajustar os imports do módulo: `from forge.narracao.fatiar import extrair_rubrica, fatiar, texto_narravel`. `sanear_texto` deixa de ser usado aqui — o texto não passa mais pelo modelo, então não há tag inventada para limpar; remover o import e dizer isso num comentário curto no topo do módulo.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/agents/test_midia.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte**

Run: `uv run pytest`
Expected: PASS. `tests/test_cli.py` monkeypatcha `planejar_midia` e não deve quebrar; conferir.

- [ ] **Step 6: Provar contra o roteiro real**

```bash
uv run python -c "
import re
from pathlib import Path
from forge.domain.models import Roteiro, Secao
from forge.agents.midia import _conferir_cobertura
from forge.narracao.fatiar import fatiar
p = sorted(Path('output/runs').glob('20260906-183127-*'))[0] / '03-write-r2.md'
t = p.read_text(encoding='utf-8')
secoes = []
for s in re.split(r'^## ', t, flags=re.M)[1:]:
    nome, corpo = s.split(chr(10), 1)
    secoes.append(Secao(nome=nome.strip(), conteudo=corpo))
roteiro = Roteiro(tema='t', tese='t', secoes=secoes)
from forge.domain.midia import BlocoNarracao
blocos = []
for sec in roteiro.secoes:
    for txt in fatiar(sec.conteudo):
        blocos.append(BlocoNarracao(id=f'b{len(blocos)+1:03d}', secao=sec.nome, texto=txt))
_conferir_cobertura(roteiro, blocos)
print('cobertura OK:', len(blocos), 'blocos,', sum(len(b.texto.split()) for b in blocos), 'palavras')
"
```

Expected: `cobertura OK: ~35 blocos, ~1079 palavras`, sem exceção. Registrar no relatório.

- [ ] **Step 7: Atualizar o `CLAUDE.md`**

Na seção sobre o plano de mídia, substituir a descrição do fatiamento por:

```markdown
Os blocos de narração são cortados por código
([narracao/fatiar.py](src/forge/narracao/fatiar.py)), não pelo modelo: fatiar é
operação determinística, e pedi-la a um LLM custou, uma vez, 85 palavras de um
roteiro de 1079. A rubrica de cena entre parênteses e a ênfase markdown são
retiradas — nenhuma das duas é narração. `_conferir_cobertura` recusa o plano
cujos blocos não reproduzam o roteiro palavra por palavra.

O modelo é chamado uma vez por seção e só para propor os beats de imagem,
recebendo os blocos já prontos e a rubrica do autor como semente visual.
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: assemble the media plan section by section

Blocks come from the deterministic slicer and ids are assigned as they are
built, so there is no model-supplied id left to remap and _normalizar is gone.
A coverage check refuses any plan whose blocks do not reproduce the script word
for word — the previous design silently produced 85 words out of 1079 and
nothing downstream could tell.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Cobertura do spec

| Requisito | Tarefa |
|---|---|
| D12 — fatiar é código, não modelo | Task 1 |
| Rubrica de cena não é narração, mas é semente visual | Tasks 1 e 2 |
| Ênfase markdown fora do TTS | Task 1 |
| LLM chamado uma vez por seção, só para beats | Task 2 |
| Beat só aponta para bloco existente da própria seção | Task 2 |
| Cobertura palavra a palavra é verificada e falha alto | Task 3 |
| Tags de emoção saem desta versão (catálogo permanece) | Task 3, ao remover `sanear_texto` do caminho |

Fora deste plano: o `verificar` do revisor e a realimentação do acervo (plano `2026-09-06-verificar-e-lacunas.md`, escrito e não executado), S5, S6, S7 e S9.
