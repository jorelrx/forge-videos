"""O plano de mídia: a ponte entre o roteiro aprovado e a execução do vídeo.

É o último artefato que exige LLM. Depois dele, narração e imagem são pura
execução — nenhuma chamada de modelo acontece na fase de GPU.
"""

from pydantic import BaseModel, Field


class BlocoNarracao(BaseModel):
    """Um trecho de 1 a 3 frases, com as tags de controle do TTS."""

    id: str
    secao: str
    texto: str


class Beat(BaseModel):
    """Uma imagem e o ponto da narração em que ela entra."""

    id: str
    bloco_id: str
    prompt: str


class PlanoMidia(BaseModel):
    blocos: list[BlocoNarracao] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
