from pathlib import Path

from forge.domain.execucao import GateResult, RunSnapshot, StageExecutionResult
from forge.domain.models import Fonte, Roteiro, Secao
from forge.domain.operacao import StageName
from forge.agents.research import ResearchBundle
from forge.executors.roteiro import ScriptExecutor
from forge.infrastructure.config import Settings
from forge.services.persistencia import gravar_modelo


def _snapshot(tmp_path: Path) -> RunSnapshot:
    root = tmp_path / "runs"
    return RunSnapshot(
        run_id="run-1", video_id="video-1", tema="Tema", tese="Tese",
        stage=StageName.ROTEIRO, attempt=1, output_root=root,
        run_dir=root / "run-1", config_snapshot={}, artifacts=[], work_items=[],
    )


def test_prepare_hash_includes_research_artifact_and_preset(tmp_path):
    context = _snapshot(tmp_path)
    executor = ScriptExecutor(settings=Settings(_env_file=None))
    first = executor.prepare(context)
    context.artifacts.append({
        "id": "a1", "run_id": "run-1", "stage_run_id": "s1",
        "kind": "research_bundle", "relative_path": "video/research.json",
        "sha256": "a" * 64, "size_bytes": 1, "mime_type": "application/json",
        "metadata": {}, "is_current": True, "created_at": "2026-09-13T00:00:00Z",
    })
    second = executor.prepare(context)
    assert first.input_hash != second.input_hash


def test_validate_rejects_script_even_when_model_review_was_optimistic(tmp_path):
    executor = ScriptExecutor(settings=Settings(_env_file=None))
    executor._roteiro = {"tema": "Tema", "tese": "Tese", "secoes": [{"nome": "Gancho", "conteudo": "curto"}]}
    result = StageExecutionResult(current_items=1, total_items=1)
    gate = executor.validate(_snapshot(tmp_path), executor.prepare(_snapshot(tmp_path)), result)
    assert not gate.approved
    assert gate.code == "script_gate_failed"
    assert any(finding.code == "script_sections_invalid" for finding in gate.findings)


def test_execute_passes_reentered_research_evidence_to_gate(tmp_path, monkeypatch):
    context = _snapshot(tmp_path)
    context.run_dir.mkdir(parents=True)
    initial = {"path": "1/ch1/p1", "title": "Fonte inicial", "authors": ["Autor 1"], "text": "x"}
    reentered = {"path": "2/ch2/p2", "title": "Fonte dirigida", "authors": ["Autor 2"], "text": "y"}
    bundle = ResearchBundle(
        brief="brief", fontes=[Fonte(titulo="Fonte inicial", autor="Autor 1", path="1/ch1/p1")],
        raw_markdown="raw", passages=[initial], passage_count=1,
        canonical_paths=["1/ch1/p1"],
    )
    gravar_modelo(context.run_dir / "video" / "research.json", bundle)

    roteiro = Roteiro(
        tema="Tema", tese="Tese",
        secoes=[Secao(nome=name, conteudo="Autor 2 sustenta esta ideia com clareza.") for name in [
            "Gancho", "Estake", "Tensao", "Virada", "Filosofo", "Prova",
            "Espelho", "Aplicacao", "Fecho",
        ]],
    )

    class Graph:
        def invoke(self, state):
            return {"roteiro": roteiro, "research_passages": [reentered]}

    monkeypatch.setattr("forge.executors.roteiro.build_graph", lambda *args, **kwargs: Graph())
    executor = ScriptExecutor(settings=Settings(_env_file=None), model=object())
    executor.execute(context, executor.prepare(context), lambda **event: None)
    assert executor._passages_by_section["Prova"][0].path == "2/ch2/p2"


def test_retry_resumes_saved_draft_at_review_instead_of_rewriting(tmp_path, monkeypatch):
    from forge.services.artefatos import gravar_artefato
    from forge.domain.roteiro import SECOES_NOMES

    context = _snapshot(tmp_path).model_copy(update={"attempt": 2})
    context.run_dir.mkdir(parents=True)
    bundle = ResearchBundle(brief="brief", fontes=[], raw_markdown="raw", passages=[], passage_count=0, canonical_paths=[])
    gravar_modelo(context.run_dir / "video/research.json", bundle)
    gravar_artefato(context.run_dir, "plan", {"tese":"Tese salva", "esboco":"Esboço salvo", "eixo":"autoconhecimento"})
    roteiro = Roteiro(tema=context.tema,tese="Tese salva",secoes=[Secao(nome=n,conteudo="Texto salvo.") for n in SECOES_NOMES])
    gravar_artefato(context.run_dir,"write",{"roteiro":roteiro})
    captured = {}
    class Graph:
        def invoke(self, state):
            captured.update(state)
            return {"roteiro":state["roteiro"]}
    def build(*args, **kwargs):
        captured["inicio"] = kwargs["inicio"]
        return Graph()
    monkeypatch.setattr("forge.executors.roteiro.build_graph",build)
    executor=ScriptExecutor(settings=Settings(_env_file=None),model=object())
    executor.execute(context,executor.prepare(context),lambda **event:None)
    assert captured["inicio"] == "review"
    assert captured["roteiro"] == roteiro
    assert captured["esboco"] == "Esboço salvo"
    assert captured["eixo"] == "autoconhecimento"


def test_retry_ignores_draft_when_research_was_refreshed(tmp_path):
    import os
    from forge.services.artefatos import gravar_artefato
    from forge.domain.roteiro import SECOES_NOMES

    context = _snapshot(tmp_path).model_copy(update={"attempt":2})
    context.run_dir.mkdir(parents=True)
    bundle = ResearchBundle(brief="brief",fontes=[],raw_markdown="raw",passages=[],passage_count=0,canonical_paths=[])
    path = gravar_modelo(context.run_dir/"video/research.json",bundle)
    gravar_artefato(context.run_dir,"plan",{"tese":"T","esboco":"E"})
    draft=Roteiro(tema="Tema",tese="T",secoes=[Secao(nome=n,conteudo="Texto") for n in SECOES_NOMES])
    gravar_artefato(context.run_dir,"write",{"roteiro":draft})
    future=path.stat().st_mtime_ns+10_000_000_000
    os.utime(path,ns=(future,future))
    assert ScriptExecutor._resume_content(context,bundle)=={}


def test_execute_grava_citacoes_derivadas_do_roteiro(tmp_path, monkeypatch):
    """A auditoria de fontes sai junto do roteiro, sem chamada de modelo."""
    from forge.domain.models import BlocoRoteiro
    from forge.services.citacoes import carregar_citacoes

    context = _snapshot(tmp_path)
    context.run_dir.mkdir(parents=True)
    passagem = {
        "path": "4363/ch2/p7", "book_id": 4363, "title": "Beyond Good and Evil",
        "authors": ["Nietzsche, Friedrich Wilhelm"], "text": "x",
        "url": "https://www.gutenberg.org/ebooks/4363",
    }
    bundle = ResearchBundle(
        brief="brief", fontes=[], raw_markdown="raw", passages=[passagem],
        passage_count=1, canonical_paths=["4363/ch2/p7"],
    )
    gravar_modelo(context.run_dir / "video" / "research.json", bundle)
    roteiro = Roteiro(tema="Tema", tese="Tese", secoes=[Secao(
        nome="Prova", conteudo="Nietzsche desconfia da vontade de verdade.",
        blocos=[BlocoRoteiro(
            texto="Nietzsche desconfia da vontade de verdade.",
            referencias=["4363/ch2/p7"],
        )],
    )])

    class Graph:
        def invoke(self, state):
            return {"roteiro": roteiro, "research_passages": state["research_passages"]}

    monkeypatch.setattr("forge.executors.roteiro.build_graph", lambda *args, **kwargs: Graph())
    eventos = []
    executor = ScriptExecutor(settings=Settings(_env_file=None), model=object())
    result = executor.execute(
        context, executor.prepare(context), lambda **event: eventos.append(event),
    )

    citacoes = carregar_citacoes(context.run_dir)
    assert [(c.tipo, c.secao, c.obra) for c in citacoes] == [
        ("parafrase", "Prova", "Beyond Good and Evil"),
    ]
    assert citacoes[0].url == "https://www.gutenberg.org/ebooks/4363"
    artefato = next(a for a in result.artifacts if a.kind == "citacoes")
    assert artefato.relative_path == "video/citacoes.json"
    assert artefato.metadata == {"citations": 1}
    assert any(e["payload"]["kind"] == "citacoes" for e in eventos)
