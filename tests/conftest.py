import pytest
from langchain_core.messages import AIMessage


class ScriptedModel:
    """Model falso: entrega respostas pré-roteirizadas, sem rede."""

    def __init__(self, *, invoke_texts=None, structured=None):
        self.invoke_texts = list(invoke_texts or [])
        self.structured = list(structured or [])
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        item = self.invoke_texts.pop(0)
        if isinstance(item, AIMessage):
            return item
        return AIMessage(content=item)

    def with_structured_output(self, schema):
        queue = self.structured

        class _Structured:
            def invoke(self, messages):
                return queue.pop(0)

        return _Structured()


@pytest.fixture
def scripted():
    return ScriptedModel


class FakeAcervo:
    """Acervo falso: passagens fixas, sem rede. Registra as queries recebidas.

    `padrao` responde a qualquer query não mapeada — o teste de grafo não sabe
    que texto o modelo roteirizado vai emitir como query.
    """

    def __init__(self, por_query=None, candidatos=None, padrao=None, livros=None):
        self.por_query = por_query or {}
        self.candidatos = candidatos or []
        self.padrao = padrao or []
        self.chamadas = []
        self._livros = livros or []
        # Queries que simulam o acervo estourando o prazo.
        self.falhas = set()

    def buscar(self, q, **kwargs):
        self.chamadas.append(q)
        if q in self.falhas:
            from forge.services.acervo import AcervoIndisponivel

            raise AcervoIndisponivel(f"acervo não respondeu em /search: {q}")
        return self.por_query.get(q, self.padrao)

    def livros(self):
        return self._livros

    def descobrir(self, q, **kwargs):
        return self.candidatos


@pytest.fixture
def acervo_fake():
    return FakeAcervo


@pytest.fixture(autouse=True)
def lacunas_em_tmp_path(monkeypatch, tmp_path):
    r"""Nenhum teste pode alcançar `C:\dev\research\dados\` por omissão.

    Os dois caminhos de realimentação do acervo são defaults reais de
    `Settings`, apontando para dados curados do usuário. Um teste que constrói
    `Settings(_env_file=None, ...)` sem sobrescrevê-los herda o caminho de
    produção; hoje isso é inofensivo só porque as fixtures em uso sempre
    devolvem passagem, e a próxima edição óbvia (uma fixture que devolve nada)
    passaria a anexar linhas no arquivo do usuário.

    Variável de ambiente, e não monkeypatch do campo: `_env_file=None` desliga
    o `.env`, não o ambiente, então isto vale para TODA construção de
    `Settings` na suíte — inclusive as que ainda não existem. Um teste que
    precise do valor real ainda pode passá-lo explicitamente no construtor,
    que vence o ambiente.
    """
    monkeypatch.setenv("FORGE_GAPS_FILE", str(tmp_path / "unanswered_questions.txt"))
    monkeypatch.setenv(
        "FORGE_RESPOSTAS_RUINS_FILE", str(tmp_path / "respostas_ruins.jsonl")
    )


# ---------------------------------------------------------------------------
# Roteiro no tamanho do canal (11-16 min). Os alvos por seção passaram de
# dezenas para centenas de palavras; montar isso à mão em cada teste esconderia
# a intenção do teste atrás de geração de texto.
# ---------------------------------------------------------------------------

# Uma sílaba por seção, sem letra em comum entre elas: o gate compara as 18
# primeiras palavras de cada seção e reprova aberturas parecidas.
_SILABAS = {
    "Gancho": "ba", "Estake": "ce", "Tensao": "di", "Virada": "fo",
    "Filosofo": "gu", "Prova": "hy", "Espelho": "jk", "Aplicacao": "lm",
    "Fecho": "nq",
}
CAMINHO_PADRAO = "4363/ch2/p7"


def _texto_de(quantidade: int, silaba: str = "xz", final: str = ".") -> str:
    """`quantidade` palavras em frases de 12, todas dentro do teto de fala."""
    palavras = [silaba * (2 + indice % 3) for indice in range(quantidade)]
    frases = [palavras[i:i + 12] for i in range(0, quantidade, 12)]
    return " ".join(
        " ".join(frase).capitalize() + (final if i == len(frases) - 1 else ".")
        for i, frase in enumerate(frases)
    )


@pytest.fixture
def texto_de():
    return _texto_de


def _roteiro_longo(**sobrescritas):
    """Nove seções no mínimo de cada alvo (1.600 palavras), aprovadas no gate.

    `sobrescritas` troca o conteúdo de uma seção: um inteiro gera esse número
    de palavras com a sílaba da própria seção; uma string entra como está.
    """
    from forge.domain.models import BlocoRoteiro, Fonte, Roteiro, Secao
    from forge.domain.roteiro import ARQUITETURA
    from forge.narracao.fatiar import texto_narravel

    secoes = []
    for spec in ARQUITETURA:
        valor = sobrescritas.get(spec.nome, spec.alvo_palavras[0])
        if isinstance(valor, int):
            valor = _texto_de(
                valor, _SILABAS[spec.nome], "?" if spec.nome == "Espelho" else "."
            )
        referencias = [] if spec.nome == "Gancho" else [CAMINHO_PADRAO]
        secoes.append(Secao(
            nome=spec.nome, conteudo=valor,
            blocos=[BlocoRoteiro(texto=texto_narravel(valor), referencias=referencias)],
        ))
    return Roteiro(
        tema="Tema", tese="Tese", secoes=secoes,
        fontes=[Fonte(
            titulo="Beyond Good and Evil", autor="Nietzsche, Friedrich Wilhelm",
            path=CAMINHO_PADRAO, book_id=4363,
            url="https://www.gutenberg.org/ebooks/4363",
        )],
    )


@pytest.fixture
def roteiro_longo():
    return _roteiro_longo


def _secoes_draft(referencia=None, **sobrescritas):
    """Nove rascunhos de seção, na ordem do contrato — um por chamada do `write`.

    Curto de propósito: o tamanho é assunto do gate, não do escritor. Com
    `referencia`, toda seção factual (todas menos o Gancho) cita esse caminho.
    """
    from forge.domain.models import BlocoRoteiro, SecaoDraft
    from forge.domain.roteiro import SECOES_NOMES

    drafts = []
    for nome in SECOES_NOMES:
        if nome in sobrescritas:
            drafts.append(sobrescritas[nome])
            continue
        texto = f"{nome} fala."
        referencias = [referencia] if referencia and nome != "Gancho" else []
        drafts.append(SecaoDraft(
            conteudo=texto, blocos=[BlocoRoteiro(texto=texto, referencias=referencias)],
        ))
    return drafts


@pytest.fixture
def secoes_draft():
    return _secoes_draft
