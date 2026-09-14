from __future__ import annotations

from fastapi import HTTPException

from pydantic import BaseModel


class ApiErrorDetail(BaseModel):
    code: str
    message: str


class ApiError(BaseModel):
    error: ApiErrorDetail


def transition_error(detail: str) -> HTTPException:
    """Transição de estado inválida -> 409."""
    raise HTTPException(
        status_code=409,
        detail={
            "error": {
                "code": "transition_invalid",
                "message": detail,
            }
        },
    )


def not_found(resource: str, identifier: str) -> HTTPException:
    """Recurso não encontrado -> 404."""
    raise HTTPException(
        status_code=404,
        detail={
            "error": {
                "code": "not_found",
                "message": f"{resource} '{identifier}' not found",
            }
        },
    )


def validation_error(detail: str) -> HTTPException:
    """Erro de validação -> 422."""
    raise HTTPException(
        status_code=422,
        detail={
            "error": {
                "code": "validation_error",
                "message": detail,
            }
        },
    )


def read_only_error(detail: str) -> HTTPException:
    """Run somente-leitura -> 409."""
    raise HTTPException(
        status_code=409,
        detail={
            "error": {
                "code": "read_only",
                "message": detail,
            }
        },
    )
