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


class Secao(BaseModel):
    nome: str
    conteudo: str


class Roteiro(BaseModel):
    tema: str
    tese: str
    secoes: list[Secao]
    fontes: list[Fonte] = Field(default_factory=list)


class Nota(BaseModel):
    dimensao: str
    problema: str
    sugestao: str


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


class Plano(BaseModel):
    tese: str
    esboco: str


class VeredictoRelevancia(BaseModel):
    """Quais passagens do acervo realmente respondem ao que se perguntou.

    Índices, não caminhos: pedir ao modelo que copie `4363/ch2/p7` corretamente é
    convidar erro de transcrição; um número ele acerta.
    """

    relevantes: list[int] = Field(default_factory=list)
    motivo: str = ""


class RoteiroDraft(BaseModel):
    secoes: list[Secao]
    falta_pesquisa: str | None = Field(
        default=None,
        description="Preencher se o material de pesquisa não sustenta alguma seção.",
    )
