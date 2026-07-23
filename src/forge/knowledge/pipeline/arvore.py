"""Marcas + segmentação -> árvore estrutural de Chunks.

Determinística, sem LLM. A árvore é a fonte da verdade estrutural: ela existe
independentemente de qualquer análise semântica e sobrevive a troca de modelo.

Só a folha-parágrafo guarda `texto`. Os outros níveis guardam offsets e derivam
o texto de `documentos.texto` via `texto_de` — evita guardar o livro inteiro
quatro vezes e alinha o índice léxico à granularidade do embedding.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    NIVEL_FOLHA,
    Chunk,
    Nivel,
    caminho_filho,
    id_de_chunk,
)
from forge.knowledge.pipeline.segmentar import paragrafos, sentencas
from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido, pagina_de_offset

logger = get_logger(__name__)

# Marca nível 1 vira capítulo, 2 vira subcapítulo, 3+ vira seção.
_NIVEL_DE_MARCA: dict[int, Nivel] = {1: "capitulo", 2: "subcapitulo"}


def _nivel_estrutural(nivel_marca: int) -> Nivel:
    return _NIVEL_DE_MARCA.get(nivel_marca, "secao")


def texto_de(documento_texto: str, chunk: Chunk) -> str:
    """Texto de qualquer nó, por offset. Para parágrafo é igual a `chunk.texto`."""
    return documento_texto[chunk.offset_inicio:chunk.offset_fim]


class _Construtor:
    def __init__(self, documento_id: str, extraido: TextoExtraido, min_chars: int):
        self.documento_id = documento_id
        self.texto = extraido.texto
        self.paginas = extraido.paginas
        self.min_chars = min_chars
        self.chunks: list[Chunk] = []
        self.ocorrencias: dict[str, int] = {}
        # Ordem do próximo filho, por pai. Um mesmo pai recebe capítulos e
        # parágrafos soltos (prefácio); se cada laço contasse do 1, dois filhos
        # diferentes acabariam com o mesmo caminho materializado.
        self.contadores: dict[str, int] = {}

    def _proxima_ordem(self, pai: Chunk) -> int:
        ordem = self.contadores.get(pai.id, 0) + 1
        self.contadores[pai.id] = ordem
        return ordem

    def _novo(
        self, *, nivel: Nivel, caminho: str, ordem: int, pai_id: str | None,
        inicio: int, fim: int, titulo: str | None = None,
    ) -> Chunk:
        conteudo = self.texto[inicio:fim]
        ocorrencia = self.ocorrencias.get(conteudo, 0)
        self.ocorrencias[conteudo] = ocorrencia + 1
        chunk = Chunk(
            id=id_de_chunk(self.documento_id, conteudo, ocorrencia),
            documento_id=self.documento_id,
            pai_id=pai_id,
            nivel=nivel,
            caminho=caminho,
            ordem=ordem,
            titulo=titulo,
            texto=conteudo if nivel == NIVEL_FOLHA else None,
            pagina=pagina_de_offset(self.paginas, inicio),
            offset_inicio=inicio,
            offset_fim=fim,
        )
        self.chunks.append(chunk)
        return chunk

    def _folhas(self, pai: Chunk, inicio: int, fim: int) -> None:
        """Parágrafos do intervalo e as sentenças de cada um."""
        for p_inicio, p_fim in paragrafos(
            self.texto, inicio, fim, min_chars=self.min_chars
        ):
            ordem = self._proxima_ordem(pai)
            paragrafo = self._novo(
                nivel=NIVEL_FOLHA, caminho=caminho_filho(pai.caminho, ordem),
                ordem=ordem, pai_id=pai.id, inicio=p_inicio, fim=p_fim,
            )
            for s_inicio, s_fim in sentencas(self.texto, p_inicio, p_fim):
                s_ordem = self._proxima_ordem(paragrafo)
                self._novo(
                    nivel="sentenca",
                    caminho=caminho_filho(paragrafo.caminho, s_ordem),
                    ordem=s_ordem, pai_id=paragrafo.id,
                    inicio=s_inicio, fim=s_fim,
                )


def _fim_da_marca(marcas: list[Marca], indice: int, limite: int) -> int:
    """Uma marca vai até a próxima de nível igual ou mais alto."""
    atual = marcas[indice]
    for seguinte in marcas[indice + 1:]:
        if seguinte.nivel <= atual.nivel:
            return seguinte.offset
    return limite


def construir_arvore(
    documento_id: str, extraido: TextoExtraido, *, paragrafo_min_chars: int = 40
) -> list[Chunk]:
    construtor = _Construtor(documento_id, extraido, paragrafo_min_chars)
    texto = extraido.texto
    marcas = sorted(extraido.marcas, key=lambda m: m.offset)

    raiz = construtor._novo(
        nivel="livro", caminho=caminho_filho("", 1), ordem=1,
        pai_id=None, inicio=0, fim=len(texto),
    )

    if not marcas:
        construtor._folhas(raiz, 0, len(texto))
        logger.info("Árvore montada", doc=documento_id, nos=len(construtor.chunks), marcas=0)
        return construtor.chunks

    # Texto antes do primeiro cabeçalho (prefácio, epígrafe) pendura na raiz.
    if marcas[0].offset > 0:
        construtor._folhas(raiz, 0, marcas[0].offset)

    # Pilha de (nivel_da_marca, chunk) para achar o pai correto de cada marca.
    pilha: list[tuple[int, Chunk]] = [(0, raiz)]
    for indice, marca in enumerate(marcas):
        while len(pilha) > 1 and pilha[-1][0] >= marca.nivel:
            pilha.pop()
        _, pai = pilha[-1]

        ordem = construtor._proxima_ordem(pai)
        fim = _fim_da_marca(marcas, indice, len(texto))
        no = construtor._novo(
            nivel=_nivel_estrutural(marca.nivel),
            caminho=caminho_filho(pai.caminho, ordem),
            ordem=ordem, pai_id=pai.id, inicio=marca.offset, fim=fim,
            titulo=marca.titulo,
        )
        pilha.append((marca.nivel, no))

        # Corpo próprio da marca: do fim do cabeçalho até o próximo cabeçalho,
        # seja qual for o nível dele.
        proximo = marcas[indice + 1].offset if indice + 1 < len(marcas) else len(texto)
        corpo_inicio = marca.offset + marca.comprimento
        if proximo > corpo_inicio:
            construtor._folhas(no, corpo_inicio, proximo)

    logger.info(
        "Árvore montada", doc=documento_id,
        nos=len(construtor.chunks), marcas=len(marcas),
    )
    return construtor.chunks
