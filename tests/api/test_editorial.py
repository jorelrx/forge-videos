from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from forge.api.contracts import CreateVideoRequest
from forge.api.routes.publication import get_performance, save_performance
from forge.api.routes.runs import create_video, review_opening, select_editorial_proposal
from forge.domain.editorial import DecisaoAbertura, EscolhaEditorial
from forge.domain.execucao import ArtifactOutput
from forge.domain.operacao import StageName, StageResult
from forge.services.control_plane import TransicaoInvalida
from forge.services.desempenho import Medicao
from forge.services.persistencia import gravar_modelo
from forge.services.publicacao import EstadoPublicacao
from forge.services.worker import StudioWorker


class Etapa:
    def __init__(self, output=None):
        self.output = output
        self.snapshots = []

    def execute(self, context, emit):
        self.snapshots.append(context.run.config_snapshot)
        if self.output is None:
            return StageResult()
        path = context.run_dir / self.output.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"artefato da etapa")
        payload = self.output.model_dump(mode="json")
        emit(kind="artifact.created", level="info", message="Arquivo pronto", payload=payload)
        return StageResult(outputs={"artifacts": [payload]})


def _proposta(titulo):
    return {
        "titulo": titulo, "situacao": "Uma dúvida cotidiana", "pergunta": titulo + "?",
        "virada": "A escolha depende da atitude", "fecho": "Retomar a dúvida",
        "thumbnail": "Um relógio", "fonte": "123/ch1/p2",
    }


def _request(services):
    from forge.services.sessao_studio import SessaoStudio
    token = SessaoStudio(services.commands.db).criar("pessoa", "Pessoa")
    with services.commands.db.transaction() as conn:
        conn.execute("INSERT INTO acesso_canais(conta_id, canal_id, titulo) VALUES ('pessoa', 'UC1', 'Canal')")
    return Request({"type": "http", "method": "GET", "query_string": b"", "path": "/",
                    "headers": [(b"cookie", f"forge_sessao={token}".encode())],
                    "app": SimpleNamespace(state=SimpleNamespace(services=services, sessoes=SessaoStudio(services.commands.db)))})


def test_run_pausa_para_recorte_e_previa_e_so_reprocessa_ajuste(services, settings):
    propostas = ArtifactOutput(
        kind="propostas_editoriais", relative_path="video/propostas.json", mime_type="application/json",
        metadata={"propostas": [_proposta("Primeira"), _proposta("Segunda")]},
    )
    previa = ArtifactOutput(
        kind="previa_abertura", relative_path="video/previa.mp4", mime_type="video/mp4",
        metadata={"itens_audio": [{"id": "b001", "texto": "trecho"}], "itens_imagem": []},
    )
    roteiro, midia = Etapa(), Etapa(previa)
    worker = StudioWorker(
        services.commands.db, worker_id="teste", lease_seconds=45,
        executors={
            StageName.PREPARACAO: Etapa(), StageName.PESQUISA: Etapa(propostas),
            StageName.ROTEIRO: roteiro, StageName.PLANO_MIDIA: midia, StageName.AUDIO: Etapa(),
        },
        now=lambda: datetime.now(UTC), runs_root=settings.studio_runs_dir,
    )
    request = _request(services)
    run_id = create_video(CreateVideoRequest(tema="Liberdade", revisao_editorial=True), request).run.id
    worker.run_once()
    assert worker.run_once().status == "paused"
    view = services.queries.get_run(run_id)
    assert view.current_stage == "roteiro"
    with pytest.raises(TransicaoInvalida):
        services.commands.request_resume(run_id, idempotency_key="tentativa")

    id_propostas = next(a.id for a in view.artifacts if a.kind == "propostas_editoriais")
    escolha = EscolhaEditorial(artefato_id=id_propostas, indice=1)
    assert select_editorial_proposal(run_id, escolha, request).status == "queued"
    worker.run_once()
    assert roteiro.snapshots[0]["proposta_editorial"]["titulo"] == "Segunda"
    assert worker.run_once().status == "paused"
    view = services.queries.get_run(run_id)
    id_previa = next(a.id for a in view.artifacts if a.kind == "previa_abertura")
    assert view.current_stage == "audio"
    with pytest.raises(HTTPException) as erro:
        review_opening(run_id, DecisaoAbertura(artefato_id=id_previa, acao="audio", item="b999"), request)
    assert erro.value.status_code == 409
    assert review_opening(
        run_id, DecisaoAbertura(artefato_id=id_previa, acao="audio", item="b001"), request,
    ).status == "queued"
    assert worker.run_once().status == "paused"
    assert len(roteiro.snapshots) == 1
    assert midia.snapshots[1]["ajustes_abertura"]["audio"]["b001"]["revisao"] == 1
    with pytest.raises(HTTPException) as erro:
        review_opening(run_id, DecisaoAbertura(artefato_id=id_previa, acao="aprovar"), request)
    assert erro.value.status_code == 409
    nova_previa = next(a for a in services.queries.get_run(run_id).artifacts if a.kind == "previa_abertura")
    aprovada = review_opening(run_id, DecisaoAbertura(artefato_id=nova_previa.id, acao="aprovar"), request)
    assert aprovada.config_snapshot["previa_aprovada_sha256"] == nova_previa.sha256
    assert worker.run_once().status == "running"


def test_desempenho_persiste_janelas_e_versao_do_video(services, settings):
    pasta = settings.studio_runs_dir / "run-1" / "video"
    gravar_modelo(pasta / "publicacao.json", EstadoPublicacao(
        etapa="concluida", video_id="vid-1", titulo="Título publicado",
        fluxo_geracao="comentarios", abertura_sha256="hash-da-abertura",
    ))
    request = _request(services)
    for janela, views in [(7, 200), (28, 500), (7, 250)]:
        save_performance("run-1", Medicao(janela=janela, visualizacoes=views, comentarios=5), request)
    dados = get_performance("run-1", request)
    assert dados["video_id"] == "vid-1"
    assert dados["fluxo_geracao"] == "comentarios"
    assert dados["abertura_sha256"] == "hash-da-abertura"
    assert [(m["janela"], m["comentarios_por_mil"]) for m in dados["medicoes"]] == [(7, 20), (28, 10)]
