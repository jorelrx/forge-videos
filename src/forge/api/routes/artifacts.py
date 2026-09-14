from __future__ import annotations

from fastapi import APIRouter, HTTPException
from forge.api.contracts import ArtifactResponse

artifacts_router = APIRouter()


@artifacts_router.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str) -> list:
    return []


@artifacts_router.get("/artifacts/{artifact_id}/content")
async def artifact_content(artifact_id: str):
    # Segurança: rejeita path traversal no artifact_id; MIME seguro; range parse
    import mimetypes
    from pathlib import Path
    safe_id = Path(artifact_id).name
    if safe_id != artifact_id or ".." in artifact_id or artifact_id.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="invalid artifact id")
    mime, _ = mimetypes.guess_type(str(safe_id))
    allowed = {"text/plain", "image/png", "image/jpeg", "application/json"}
    if mime and mime not in allowed:
        raise HTTPException(status_code=415, detail="unsupported mime type")
    # Range parse de exemplo (stub para futura integração de Range header)
    from forge.api.ranges import parse_range, RangeNotSatisfiable
    try:
        parse_range("bytes=0-", 1024)
    except RangeNotSatisfiable:
        pass
    return {"id": artifact_id, "mime": mime or "application/octet-stream"}
