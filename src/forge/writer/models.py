from pydantic import BaseModel, Field

SECOES_NOMES: list[str] = [
    "Hook", "Problema", "História", "Explicação", "Filósofo",
    "Psicologia", "Aplicação", "Resumo", "Conclusão",
]


class Fonte(BaseModel):
    titulo: str
    autor: str | None = None
    url: str | None = None
    frase: str | None = None


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


class FonteList(BaseModel):
    fontes: list[Fonte] = Field(default_factory=list)


class Plano(BaseModel):
    tese: str
    esboco: str


class RoteiroDraft(BaseModel):
    secoes: list[Secao]
