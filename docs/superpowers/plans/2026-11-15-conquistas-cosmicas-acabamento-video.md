# Acabamento do vídeo (frente 2) — plano de implementação

> **Para quem executa:** tarefas 2–6 são independentes e vão para subagentes em
> paralelo; 1, 7, 8 e 9 ficam com o gerente da sessão. TDD em todas.

**Objetivo:** vídeo final com crossfade, trilha, fonte na tela, legenda `.srt`,
capítulos reais, thumbnail pronta e aba Publicação.

**Arquitetura:** lógica nova em módulos puros de `services/`; `executors/ffmpeg.py`
ganha os comandos; `executors/montagem.py` e `executors/imagens.py` só
orquestram. Nenhuma etapa nova no Studio, nenhuma chamada de modelo.

**Spec:** [2026-11-15-conquistas-cosmicas-acabamento-video-design.md](../specs/2026-11-15-conquistas-cosmicas-acabamento-video-design.md)

## Restrições globais

- Sem `git commit`, `stash`, `checkout`, `reset`, `add`. A árvore tem trabalho
  não commitado de outra frente.
- Cada tarefa toca só os arquivos que lista.
- `ffmpeg`/`ffprobe` por injeção (`runner`); teste de unidade não codifica.
- Docstrings e comentários em português, explicando o porquê.
- Log por `get_logger(__name__)`, campos chave=valor, sem f-string.
- Falta de trilha, cartão, fonte de letra ou embalagem nunca derruba a run.
- Testes: `uv run pytest <arquivo>`; sem rede.

## Foco da revisão

1. Texto de cartão ou legenda com `{`, `}`, `\` ou quebra de linha: não pode
   virar comando ASS nem quebrar o SRT.
2. Bloco de narração muito curto (< 1 s) ou com uma frase enorme: legenda
   continua crescente e sem sobreposição.
3. Vídeo com um único beat: sem `xfade`, ainda com fade de abertura e fim.
4. Caminho com espaço, apóstrofo ou `C:` no filtro `ass` do FFmpeg.
5. Trilha mais curta que o vídeo (loop) e mais longa (corte com fade).

---

## Tarefa 1 — Configuração e linha do tempo (gerente)

**Arquivos:** `src/forge/infrastructure/config.py`, `.env.example`,
`src/forge/services/linha_tempo.py`, `tests/services/test_linha_tempo.py`

**Produz:**

```python
# config.Settings
trilhas_dir: Path = Path("library/trilhas")
trilha_volume_db: float = -20.0
crossfade_segundos: float = 0.6
fonte_video: str = "Georgia"
fonte_thumbnail: Path = Path(r"C:\Windows\Fonts\georgiab.ttf")

# services/linha_tempo.py
class TrechoTempo(BaseModel):
    bloco_id: str
    secao: str
    inicio: float
    fim: float

def linha_do_tempo(blocos: list[BlocoNarracao], duracoes: dict[str, float]) -> list[TrechoTempo]
# Na ordem recebida, acumulando. Bloco sem duração levanta KeyError.

def inicio_das_secoes(tempos: list[TrechoTempo]) -> dict[str, float]
# Início do primeiro bloco de cada seção, na ordem de aparição.
```

## Tarefa 2 — Legenda (subagente)

**Arquivos:** `src/forge/services/legendas.py`, `tests/services/test_legendas.py`

**Consome:** `TrechoTempo`, `BlocoNarracao`, `forge.narracao.fatiar.dividir_frases`
e `texto_narravel`; o que `forge.narracao.tags` oferecer para tirar tags de TTS.

**Produz:**

```python
LINHA_MAXIMO = 42
LINHAS_MAXIMO = 2
DEIXA_MINIMO_SEGUNDOS = 1.0

class Deixa(BaseModel):
    inicio: float
    fim: float
    texto: str            # até duas linhas, separadas por "\n"

def gerar_deixas(blocos: list[BlocoNarracao], tempos: list[TrechoTempo]) -> list[Deixa]
def formatar_srt(deixas: list[Deixa]) -> str      # "00:00:01,500 --> 00:00:04,000"
def conferir_deixas(deixas: list[Deixa]) -> list[str]   # problemas; vazio = ok
```

Regras: tempo do bloco repartido entre as deixas pela contagem de caracteres;
frase acima de 84 caracteres vira mais de uma deixa, cortada em vírgula ou, na
falta, em espaço; nenhuma palavra perdida (o teste junta as deixas e compara com
o texto falado); bloco curto demais para dar 1 s a cada deixa funde as deixas
até caber; tempos crescentes, sem sobreposição, última deixa do bloco termina no
fim do bloco. Bloco sem tempo correspondente é pulado.

## Tarefa 3 — Cartões de fonte (subagente)

**Arquivos:** `src/forge/services/cartoes.py`, `tests/services/test_cartoes.py`

**Consome:** `TrechoTempo`; `BlocoNarracao.referencias` (caminhos de passagem) e
`.citacoes_literais` (`CitacaoLiteral`: `path`, `trecho`, `traducao`);
`forge.services.citacoes.Citacao` (dá `path` → `autor`, `obra`).

**Produz:**

```python
RODAPE_SEGUNDOS = 6.0
CITACAO_MAXIMO = 220

class Cartao(BaseModel):
    tipo: Literal["rodape", "citacao"]
    inicio: float
    fim: float
    atribuicao: str       # "Autor — Obra", ou só a obra sem autor
    texto: str = ""       # só em "citacao": o trecho falado
    traducao: bool = False

def planejar_cartoes(
    blocos: list[BlocoNarracao], tempos: list[TrechoTempo], citacoes: list[Citacao],
) -> list[Cartao]
def gerar_ass(cartoes: list[Cartao], *, fonte: str, largura: int = 1920, altura: int = 1080) -> str
```

Regras: literal ou tradução até 220 caracteres vira `citacao` pela duração do
bloco (texto = `traducao` se houver, senão `trecho`); acima disso, `rodape`.
Paráfrase vira `rodape` de até 6 s (nunca passando do fim do bloco), só quando a
obra muda em relação ao último cartão ou é a primeira citação da seção. Caminho
sem entrada em `citacoes` não gera cartão. No máximo um cartão por bloco;
`citacao` ganha de `rodape`. Cartões nunca se sobrepõem. ASS: cabeçalho
`PlayResX/Y`, estilo de rodapé (canto inferior esquerdo, discreto) e de citação
(centro, caixa escura translúcida, atribuição em linha própria, `tradução livre`
quando for o caso); texto escapado (`{`, `}`, `\`, quebras de linha).

## Tarefa 4 — Trilha e thumbnail (subagente)

**Arquivos:** `src/forge/services/trilha.py`, `tests/services/test_trilha.py`,
`src/forge/services/thumbnail.py`, `tests/services/test_thumbnail.py`

**Produz:**

```python
# trilha.py
EXTENSOES = (".mp3", ".wav", ".flac", ".ogg", ".m4a")

class Trilha(BaseModel):
    caminho: Path
    credito: str | None = None     # primeira linha não vazia de <faixa>.txt

def escolher_trilha(pasta: Path, *, semente: str, eixo: str | None = None) -> Trilha | None
# Subpasta `eixo` com faixas tem preferência; senão a raiz (sem recursão).
# Índice = sha256(semente) sobre a lista ordenada por nome. Pasta ausente/vazia: None.

# thumbnail.py
LARGURA, ALTURA = 1280, 720
BYTES_MAXIMO = 2_000_000

class ThumbnailInfo(BaseModel):
    largura: int
    altura: int
    bytes: int
    com_texto: bool

def compor_thumbnail(base: Path, texto: str, saida: Path, *, fonte: Path | None) -> ThumbnailInfo
```

Thumbnail: redimensiona cobrindo e corta ao centro para 1280×720; gradiente
escuro no lado esquerdo; texto em até duas linhas, o maior tamanho que caiba em
~55% da largura, branco com contorno escuro; JPEG com qualidade descendo de 92
até caber em 2 MB. `fonte` ausente ou ilegível, ou texto vazio: sai sem texto,
`com_texto=False`, sem exceção.

## Tarefa 5 — Comandos de FFmpeg (subagente)

**Arquivos:** `src/forge/executors/ffmpeg.py`, `tests/executors/test_ffmpeg.py`
(ou o arquivo de teste que já cobre o módulo), `tests/executors/test_ffmpeg_real.py`

**Produz:**

```python
def build_ken_burns_filter(seconds, index, portrait=False, *, fade=FADE_PADRAO,
                           fade_in: float | None = None, fade_out: float | None = None) -> str
# fade_in/fade_out None mantêm o comportamento atual (ambos = fade). 0 = sem fade.

def clip_from_image(imagem, saida, *, seconds, index, portrait,
                    fade_in: float | None = None, fade_out: float | None = None, runner=run_ffmpeg) -> None

def crossfade_videos(clipes: list[Path], duracoes: list[float], saida: Path, *,
                     crossfade: float, legendas_ass: Path | None = None, runner=run_ffmpeg) -> None
# duracoes = duração NOMINAL de cada clipe; o arquivo de cada clipe, menos o
# último, tem `crossfade` a mais. Transição i começa em soma(duracoes[:i+1]).
# Duração da saída = soma(duracoes). Clipe nominal < 2*crossfade: corte seco
# naquela junção. Um clipe só: sem xfade. `legendas_ass` queimado no mesmo
# passe; o comando roda com cwd na pasta do .ass e usa o nome relativo, para
# não escapar `C:` no filtro.

def mix_audio(narracao: Path, trilha: Path | None, saida: Path, *, duracao: float,
              volume_db: float, runner=run_ffmpeg) -> None
# Narração com loudnorm I=-14; trilha em loop (-stream_loop -1), volume-base,
# fade in 2 s / out 4 s, sidechaincompress pela narração, amix, cortado em
# `duracao`. Sem trilha: só a narração normalizada. Saída WAV 48 kHz estéreo.
```

Teste real (pula sem `ffmpeg` no PATH): três imagens e três WAVs sintéticos
gerados no teste; confere duração da saída = soma das nominais (±0,1 s), que o
quadro do meio de uma transição não é preto, e que `mix_audio` com trilha mais
curta que a narração produz áudio da duração pedida.

## Tarefa 6 — Aba Publicação (subagente)

**Arquivos:** `web/` (componente novo `publication.tsx` + teste, navegação em
`dashboard.tsx`, cliente em `lib/api.ts` se preciso, CSS), e
`src/forge/api/routes/artifacts.py` + teste de API para servir `.srt`.

Ler `web/AGENTS.md` e `web/CLAUDE.md` antes. Artefatos que a aba consome, por
`kind`: `embalagem` (JSON, formato de `forge.domain.embalagem.Embalagem`),
`thumbnail.jpg` (`image/jpeg`), `legendas.srt` (`application/x-subrip`),
`video/final.mp4`. Conteúdo conforme a seção 8 do spec. Artefato ausente mostra
estado vazio, nunca erro.

## Tarefa 7 — Capítulos reais na embalagem (gerente)

**Arquivos:** `src/forge/domain/embalagem.py`, `src/forge/agents/embalagem.py`,
`tests/agents/test_embalagem.py`

`Embalagem` ganha `abertura`, `resumo`, `musica`. Novo:

```python
def aplicar_tempos_reais(embalagem: Embalagem, tempos: list[TrechoTempo], *,
                         musica: str | None, aviso_ia: bool) -> Embalagem
```

Capítulo com menos de 10 s até o seguinte é fundido no anterior. Embalagem sem
`abertura` (gravada antes desta frente) volta inalterada.

## Tarefa 8 — Integração na montagem e nas imagens (gerente)

**Arquivos:** `src/forge/executors/montagem.py`, `src/forge/executors/imagens.py`,
`src/forge/executors/validacao.py` se o gate de imagem pegar a thumbnail, e os
testes dos três.

Montagem: clipes sem fade próprio e com acréscimo de crossfade; linha do tempo;
`cartoes.ass`; `legendas.srt`; trilha; `mix.wav`; passe de crossfade; mux;
embalagem com tempos reais. Artefatos novos: `legendas.srt`, `embalagem`,
`embalagem_markdown`. Avisos `trilha_ausente`, `cartoes_ausentes`,
`capitulos_estimados`. Imagens: item `thumbnail`, base com tipo
`thumbnail.base`, saída `video/thumbnail.jpg` tipo `thumbnail.jpg`.

## Tarefa 9 — Verificação, revisão e documentação (gerente)

Suíte completa; teste real de FFmpeg; revisão independente do diff desta frente
com o Foco da revisão; correções com teste; `CLAUDE.md`, `README.md`.
