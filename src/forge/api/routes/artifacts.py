from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from forge.api.ranges import parse_range, RangeNotSatisfiable, iter_file_range

artifacts_router = APIRouter()

PREVIEW_MIME = frozenset({
    "text/markdown",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/webp",
    "audio/wav",
    "video/mp4",
})


def _resolve_artifact_path(settings, artifact) -> Path:
    from forge.infrastructure.config import get_settings
    s = settings if settings is not None else get_settings()
    run_root = (Path(s.studio_runs_dir) / artifact.run_id).resolve(strict=True)
    path = (run_root / artifact.relative_path).resolve(strict=True)
    path.relative_to(run_root)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file not found")
    return path


@artifacts_router.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str) -> list:
    return []


@artifacts_router.get("/artifacts/{artifact_id}/content")
async def artifact_content(artifact_id: str, request: Request):
    # Segurança: rejeita path traversal no artifact_id
    if (
        artifact_id.startswith(("/", "\\"))
        or ".." in artifact_id.split("/")
        or artifact_id != Path(artifact_id).name
    ):
        raise HTTPException(status_code=400, detail="invalid artifact id")

    from forge.infrastructure.config import get_settings
    settings = get_settings()
    try:
        from forge.services.studio_query import StudioQueryService
        from forge.repositories.connection import Database
        db = Database(str(settings.studio_db_path))
        queries = StudioQueryService(db)
        artifact = queries.get_artifact(artifact_id)
    except Exception:
        raise HTTPException(status_code=404, detail="artifact not found")

    mime = artifact.mime_type
    if mime not in PREVIEW_MIME:
        raise HTTPException(status_code=415, detail="unsupported mime type")

    path = _resolve_artifact_path(settings, artifact)
    size = path.stat().st_size

    range_value = request.headers.get("Range")
    if not range_value:
        return FileResponse(
            path,
            media_type=mime,
            headers={"accept-ranges": "bytes"},
        )

    try:
        selected = parse_range(range_value, size)
    except RangeNotSatisfiable:
        raise HTTPException(
            status_code=416,
            detail="Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        )

    chunks = iter_file_range(path, selected)
    content = b"".join(chunks)
    return StreamingResponse(
        iter([content]),
        media_type=mime,
        status_code=206,
        headers={
            "Content-Range": f"bytes {selected.start}-{selected.end}/{size}",
            "accept-ranges": "bytes",
            "Content-Length": str(len(content)),
        },
    )
