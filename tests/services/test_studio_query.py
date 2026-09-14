from forge.domain.operacao import RunStatus, StageName
from forge.services.studio_query import StudioQueryService


def test_queue_and_history_include_video_identity_and_stable_global_progress(db):
    # Use existing repository fixture to create two videos/runs. Mark the first
    # two current stages succeeded with progress=1 and the third at 0.5.
    queries = StudioQueryService(db)

    queue = queries.list_queue()
    assert queue[0].video.tema == "Tema prioritário"
    assert queue[0].progress == 0.0

    page = queries.list_runs(limit=1, offset=0)
    assert page.total == 2
    assert page.limit == 1
    assert page.offset == 0
    assert page.items[0].current_stage is StageName.ROTEIRO
    assert page.items[0].progress == (1 + 1 + 0.5) / 8


def test_run_view_uses_only_current_attempt_and_exposes_items_metrics_and_artifacts(db):
    queries = StudioQueryService(db)
    detail = queries.get_run("run-id")

    assert len(detail.stages) == 8
    assert detail.stages[StageName.AUDIO].attempt == 2
    assert [item.item_key for item in detail.stages[StageName.AUDIO].items] == ["b001"]
    assert detail.stages[StageName.AUDIO].metrics == {"duration_ms": 900}
    assert all(artifact.is_current for artifact in detail.artifacts)


def test_unknown_run_and_artifact_raise_key_error(db):
    queries = StudioQueryService(db)
    import pytest
    with pytest.raises(KeyError):
        queries.get_run("missing")
    with pytest.raises(KeyError):
        queries.get_artifact("missing")
