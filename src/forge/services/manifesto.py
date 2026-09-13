"""Estado por item da fase de vídeo.

40 imagens numa RX 580 são horas. O manifesto existe para que um crash na
imagem 33 custe uma imagem, não a noite inteira: cada item carrega o próprio
estado e o arquivo é regravado depois de cada um.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, PrivateAttr

from forge.domain.midia import PlanoMidia
from forge.domain.operacao import ItemStatus
from forge.infrastructure.logging import get_logger
from forge.services.persistencia import carregar_modelo, gravar_modelo

logger = get_logger(__name__)

Tipo = Literal["audio", "imagem"]
Estado = Literal["pendente", "ok", "falhou"]


class Item(BaseModel):
    id: str
    tipo: Tipo
    estado: Estado = "pendente"
    entrada: dict = Field(default_factory=dict)
    saida: str = ""
    duracao_ms: int | None = None
    tentativas: int = 0
    erro: str = ""


class Manifesto(BaseModel):
    itens: list[Item] = Field(default_factory=list)
    # DB work-item ids are opaque UUIDs while the human snapshot uses the
    # stable item key (b001/i001). Keep the bridge in memory only; it is not a
    # second persisted authority.
    _work_item_ids: dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def from_work_items(cls, items: Iterable[Any]) -> "Manifesto":
        """Project operational SQLite items into the human-readable snapshot.

        ``work_items`` is authoritative for status, attempts and failures.
        The old ``manifesto.json`` is deliberately not read here, which makes
        a stale or hand-edited snapshot harmless on resume.
        """
        estado_por_status = {
            ItemStatus.PENDING.value: "pendente",
            ItemStatus.RUNNING.value: "pendente",
            ItemStatus.SUCCEEDED.value: "ok",
            ItemStatus.FAILED.value: "falhou",
            ItemStatus.INVALIDATED.value: "pendente",
        }
        projected: list[Item] = []
        work_item_ids: dict[str, str] = {}
        for work_item in items:
            value = (
                work_item.model_dump(mode="json")
                if hasattr(work_item, "model_dump")
                else dict(work_item)
            )
            item_key = str(value.get("item_key") or value.get("id") or "")
            if not item_key:
                raise ValueError("work item sem item_key")
            raw_type = value.get("tipo") or value.get("type")
            if raw_type not in {"audio", "imagem"}:
                raw_type = "audio" if item_key.startswith("b") else "imagem"
            raw_status = value.get("status", ItemStatus.PENDING.value)
            status = getattr(raw_status, "value", raw_status)
            entrada = value.get("input") or value.get("entrada") or {}
            failure = value.get("failure_message") or value.get("erro") or ""
            projected.append(
                Item(
                    id=item_key,
                    tipo=raw_type,
                    estado=estado_por_status.get(str(status), "pendente"),
                    entrada=entrada,
                    duracao_ms=value.get("duration_ms", value.get("duracao_ms")),
                    tentativas=int(value.get("attempts", value.get("tentativas", 0)) or 0),
                    erro=str(failure),
                )
            )
            if value.get("id"):
                work_item_ids[item_key] = str(value["id"])
        manifesto = cls(itens=projected)
        manifesto._work_item_ids = work_item_ids
        return manifesto

    def merge_outputs(self, artifacts: Iterable[Any]) -> "Manifesto":
        """Merge current artifact paths into this DB-derived snapshot.

        Artifact status remains owned by ``from_work_items``. This method only
        fills output details that the database artifact rows expose, and
        returns ``self`` for convenient projection pipelines.
        """
        by_id = {item.id: item for item in self.itens}
        for artifact in artifacts:
            value = (
                artifact.model_dump(mode="json")
                if hasattr(artifact, "model_dump")
                else dict(artifact)
            )
            metadata = value.get("metadata") or {}
            item_key = value.get("item_key") or metadata.get("item_key")
            work_item_id = value.get("work_item_id")
            if not item_key and work_item_id:
                item_key = next(
                    (
                        key for key, db_id in self._work_item_ids.items()
                        if db_id == str(work_item_id)
                    ),
                    None,
                )
            if not item_key:
                # ArtifactOutput (child protocol) has no DB id. Its canonical
                # per-item path still provides a safe last-resort key.
                path = str(value.get("relative_path", ""))
                stem = Path(path).stem
                if stem in by_id:
                    item_key = stem
            item = by_id.get(str(item_key)) if item_key else None
            if item is None:
                continue
            item.saida = str(value.get("relative_path") or value.get("saida") or "")
            duration = metadata.get("duration_ms", metadata.get("duracao_ms"))
            if duration is not None:
                item.duracao_ms = int(duration)
        return self


def caminho(run_dir: Path) -> Path:
    return Path(run_dir) / "video" / "manifesto.json"


def _do_plano(plano: PlanoMidia) -> Manifesto:
    itens = [
        Item(id=b.id, tipo="audio", entrada={"texto": b.texto, "secao": b.secao})
        for b in plano.blocos
    ]
    itens += [
        Item(id=i.id, tipo="imagem", entrada={"prompt": i.prompt, "bloco_id": i.bloco_id})
        for i in plano.beats
    ]
    return Manifesto(itens=itens)


def criar_ou_carregar(
    run_dir: Path,
    plano: PlanoMidia,
    *,
    work_items: Iterable[Any] | None = None,
    artifacts: Iterable[Any] | None = None,
) -> Manifesto:
    """Monta o manifesto do plano, preservando o que um run anterior já fez.

    O id vem do plano e é estável, então o estado antigo reata com o item novo
    sem ambiguidade. Porém, se a entrada mudou (ex: texto de um bloco foi editado),
    o item é resetado como pendente, pois a saída anterior não corresponde ao
    novo input. tentativas é preservada para manter histórico de falhas.

    Quando ``work_items`` vem do repositório operacional, ele é a autoridade:
    o JSON anterior deixa de participar da decisão de retomada e vira somente
    o snapshot que será reescrito.
    """
    if work_items is not None:
        manifesto = Manifesto.from_work_items(work_items)
        if artifacts is not None:
            manifesto.merge_outputs(artifacts)
        gravar(run_dir, manifesto)
        return manifesto

    novo = _do_plano(plano)
    if not caminho(run_dir).exists():
        return novo

    antigo = {i.id: i for i in carregar(run_dir).itens}
    itens = []
    for i_novo in novo.itens:
        i_antigo = antigo.get(i_novo.id)
        if i_antigo is None:
            # Item novo, não existe no run anterior
            itens.append(i_novo)
        elif i_antigo.entrada == i_novo.entrada:
            # Entrada inalterada, preserva tudo (resume case)
            itens.append(i_antigo)
        else:
            # Entrada mudou, reset para pendente mas preserva tentativas
            item_resetado = i_novo.model_copy()
            item_resetado.tentativas = i_antigo.tentativas
            itens.append(item_resetado)
            logger.warning(
                "Item entrada mudou, resetando",
                id=i_novo.id,
                estado_anterior=i_antigo.estado,
            )

    logger.info(
        "Manifesto retomado",
        total=len(itens),
        pendentes=sum(1 for i in itens if i.estado == "pendente"),
    )
    return Manifesto(itens=itens)


def carregar(run_dir: Path) -> Manifesto:
    return carregar_modelo(caminho(run_dir), Manifesto)


def gravar(run_dir: Path, manifesto: Manifesto) -> None:
    # Escrita atômica (ver services/persistencia.py): um corte de energia no
    # meio da gravação deixaria um JSON truncado no lugar do progresso de horas.
    gravar_modelo(caminho(run_dir), manifesto)


def pendentes(manifesto: Manifesto, tipo: str | None = None) -> list[Item]:
    return [
        i for i in manifesto.itens
        if i.estado == "pendente" and (tipo is None or i.tipo == tipo)
    ]
