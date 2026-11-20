from typing import Literal

from pydantic import BaseModel, Field

from forge.domain.roteiro import SECOES_NOMES



class Fonte(BaseModel):
    titulo: str
    autor: str | None = None
    url: str | None = None
    frase: str | None = None
    # Procedência no acervo. Opcionais porque runs anteriores ao acervo não
    # têm nenhum dos dois, e `--retomar` precisa continuar lendo aqueles
    # artefatos.
    path: str | None = None
    book_id: int | None = None


class CitacaoLiteral(BaseModel):
    path: str
    trecho: str
    # O acervo é de livros em inglês e alemão; a narração é em português. Com
    # `traducao`, `trecho` é o original (tem de estar na passagem) e `traducao`
    # é o que a fala diz. Sem ela, vale a regra antiga: o mesmo trecho na
    # passagem e na fala. Opcional para que runs antigas continuem carregando.
    traducao: str | None = Field(
        default=None,
        description=(
            "Tradução própria do trecho, exatamente como aparece na fala. "
            "Preencher só quando a passagem está em outro idioma."
        ),
    )


class BlocoRoteiro(BaseModel):
    texto: str
    referencias: list[str] = Field(default_factory=list)
    citacoes_literais: list[CitacaoLiteral] = Field(default_factory=list)
    # Marcadores de runs antigas permanecem explicitamente não verificados.
    referencias_legadas: list[str] = Field(default_factory=list)


class Secao(BaseModel):
    nome: str
    conteudo: str
    blocos: list[BlocoRoteiro] = Field(default_factory=list)


class Roteiro(BaseModel):
    tema: str
    tese: str
    secoes: list[Secao]
    fontes: list[Fonte] = Field(default_factory=list)


class Nota(BaseModel):
    dimensao: str
    problema: str
    sugestao: str
    secao: str | None = Field(
        default=None,
        description=(
            "Nome da seção a que a nota se aplica, um dos nove do roteiro. "
            "Vazio só quando a nota vale para o roteiro inteiro."
        ),
    )


class ReviewResult(BaseModel):
    aprovado: bool
    notas: list[Nota] = Field(default_factory=list)
    verificar: list[str] = Field(
        default_factory=list,
        description=(
            "Afirmações de fato do roteiro que você não conseguiu confirmar. "
            "Frases afirmativas e completas, nunca perguntas nem respostas de "
            "conferência. Vazio é a resposta normal."
        ),
    )


Eixo = Literal["estoicismo", "autoconhecimento", "niilismo-absurdo", "etica-digital-ia"]


class Plano(BaseModel):
    tese: str
    esboco: str
    eixo: Eixo | None = Field(
        default=None,
        description="Eixo editorial do canal em que o tema se encaixa, se algum.",
    )


class VeredictoRelevancia(BaseModel):
    """Quais passagens do acervo realmente respondem ao que se perguntou.

    Índices, não caminhos: pedir ao modelo que copie `4363/ch2/p7` corretamente é
    convidar erro de transcrição; um número ele acerta.
    """

    relevantes: list[int] = Field(default_factory=list)
    motivo: str = ""


class SecaoDraft(BaseModel):
    """O que o modelo devolve por seção. O nome não vem dele: é o código que
    sabe qual das nove seções pediu, então não há nome para canonizar nem para
    o modelo trocar."""

    conteudo: str
    blocos: list[BlocoRoteiro] = Field(default_factory=list)
    falta_pesquisa: str | None = Field(
        default=None,
        description="Preencher se o material de pesquisa não sustenta esta seção.",
    )
