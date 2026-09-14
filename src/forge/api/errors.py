from __future__ import annotations

from pydantic import BaseModel, Field


class ApiErrorDetail(BaseModel):
    code: str
    message: str


class ApiError(BaseModel):
    error: ApiErrorDetail
