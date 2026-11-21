from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, model_validator

from forge.services.persistencia import carregar_modelo, gravar_modelo
from forge.services.publicacao import EstadoPublicacao


class Medicao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    janela: Literal[7, 28]
    visualizacoes: int = Field(ge=0)
    impressoes: int | None = Field(default=None, ge=0)
    ctr: float | None = Field(default=None, ge=0, le=100)
    origem_trafego: str = Field(default="", max_length=80)
    retencao_30s: float | None = Field(default=None, ge=0, le=100)
    percentual_assistido: float | None = Field(default=None, ge=0)
    comentarios: int | None = Field(default=None, ge=0)
    respostas_lidas: int | None = Field(default=None, ge=0)
    respostas_substantivas: int | None = Field(default=None, ge=0)
    cliques_tela_final: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def amostra_consistente(self):
        if self.respostas_substantivas is not None and (
            self.respostas_lidas is None or self.respostas_substantivas > self.respostas_lidas
        ):
            raise ValueError("Respostas substantivas devem caber na amostra lida")
        return self


class MedicaoRegistrada(Medicao):
    registrado_em: str

    @property
    def comentarios_por_mil(self) -> float | None:
        if self.comentarios is None or not self.visualizacoes:
            return None
        return round(1000 * self.comentarios / self.visualizacoes, 2)

    def para_api(self) -> dict:
        return {**self.model_dump(), "comentarios_por_mil": self.comentarios_por_mil}


class Desempenho(BaseModel):
    video_id: str
    titulo: str
    canal_id: str | None = None
    fluxo_geracao: str | None = None
    abertura_sha256: str | None = None
    thumbnail_sha256: str | None = None
    medicoes: list[MedicaoRegistrada] = Field(default_factory=list)

    def para_api(self) -> dict:
        return {**self.model_dump(), "medicoes": [medicao.para_api() for medicao in self.medicoes]}


def ler_desempenho(run_dir: Path, estado: EstadoPublicacao) -> Desempenho:
    caminho = run_dir / "video" / "desempenho.json"
    if caminho.is_file():
        atual = carregar_modelo(caminho, Desempenho)
        if atual.video_id == estado.video_id:
            return atual
    return Desempenho(
        video_id=estado.video_id, titulo=estado.titulo, canal_id=estado.canal_id,
        fluxo_geracao=estado.fluxo_geracao, abertura_sha256=estado.abertura_sha256,
        thumbnail_sha256=estado.thumbnail_sha256,
    )


def salvar_medicao(run_dir: Path, estado: EstadoPublicacao, medicao: Medicao) -> Desempenho:
    caminho = run_dir / "video" / "desempenho.json"
    with FileLock(str(caminho) + ".lock", timeout=5):
        atual = ler_desempenho(run_dir, estado)
        registro = MedicaoRegistrada(
            **medicao.model_dump(), registrado_em=datetime.now(timezone.utc).isoformat(),
        )
        por_janela = {item.janela: item for item in atual.medicoes}
        por_janela[registro.janela] = registro
        atual.medicoes = [por_janela[janela] for janela in sorted(por_janela)]
        gravar_modelo(caminho, atual)
        return atual
