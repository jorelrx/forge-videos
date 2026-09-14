"""Preflight checks for forge-studio-doctor and worker startup."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from forge.infrastructure.config import Settings

PASS = "passed"
WARN = "warning"
FAIL = "failed"


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    state: str
    message: str
    action: str


@dataclass
class PreflightReport:
    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.state != FAIL for c in self.checks)


def _check_python(runner=subprocess.run) -> PreflightCheck:
    try:
        result = runner(
            [sys.executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version_line = result.stdout.strip() or result.stderr.strip()
        parts = version_line.split()
        if len(parts) >= 2:
            version_str = parts[1]
            major_minor = version_str.split(".")[:2]
            major, minor = int(major_minor[0]), int(major_minor[1])
            if (major, minor) >= (3, 12):
                return PreflightCheck(
                    name="python",
                    state=PASS,
                    message=f"Python {version_str}",
                    action="",
                )
        return PreflightCheck(
            name="python",
            state=FAIL,
            message=f"Python >=3.12 requerido (encontrado: {version_line})",
            action="Instale Python 3.12+",
        )
    except Exception as exc:
        return PreflightCheck(
            name="python",
            state=FAIL,
            message=f"Python nao encontrado: {exc}",
            action="Instale Python 3.12+",
        )


def _check_node(runner=subprocess.run) -> PreflightCheck:
    try:
        result = runner(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version_line = result.stdout.strip().lstrip("v")
        major_minor = version_line.split(".")[:2]
        major, minor = int(major_minor[0]), int(major_minor[1])
        if (major, minor) >= (20, 9):
            return PreflightCheck(
                name="node",
                state=PASS,
                message=f"Node.js {version_line}",
                action="",
            )
        return PreflightCheck(
            name="node",
            state=FAIL,
            message=f"Node.js >=20.9 requerido (encontrado: {version_line})",
            action="Instale Node.js 20.9+",
        )
    except Exception as exc:
        return PreflightCheck(
            name="node",
            state=FAIL,
            message=f"Node.js nao encontrado: {exc}",
            action="Instale Node.js 20.9+",
        )


def _check_uv(which=shutil.which) -> PreflightCheck:
    path = which("uv")
    if path:
        return PreflightCheck(name="uv", state=PASS, message=f"uv em {path}", action="")
    return PreflightCheck(
        name="uv",
        state=FAIL,
        message="uv nao encontrado no PATH",
        action="Instale uv (astral.sh/uv)",
    )


def _check_ffmpeg(which=shutil.which) -> PreflightCheck:
    ffmpeg = which("ffmpeg")
    ffprobe = which("ffprobe")
    if ffmpeg and ffprobe:
        return PreflightCheck(
            name="ffmpeg", state=PASS, message="ffmpeg e ffprobe disponiveis", action=""
        )
    missing = []
    if not ffmpeg:
        missing.append("ffmpeg")
    if not ffprobe:
        missing.append("ffprobe")
    return PreflightCheck(
        name="ffmpeg",
        state=FAIL,
        message=f"Faltam: {', '.join(missing)}",
        action="Instale ffmpeg/ffprobe",
    )


def _check_tts(settings: Settings, path_exists=Path.exists) -> PreflightCheck:
    missing = []
    for label, resolved in [
        ("tts_binary", settings.resolved_tts_binary),
        ("tts_model", settings.resolved_tts_model),
        ("tts_voice_reference", settings.resolved_tts_voice_reference),
    ]:
        if not path_exists(resolved):
            missing.append(label)
    if not missing:
        return PreflightCheck(
            name="tts", state=PASS, message="Binario, modelo e voice reference presentes", action=""
        )
    return PreflightCheck(
        name="tts",
        state=FAIL,
        message=f"Faltam: {', '.join(missing)}",
        action="Configure tts_binary, tts_model, tts_voice_reference",
    )


def _check_web(path_exists=Path.exists, base_path: Path | None = None) -> PreflightCheck:
    if base_path is None:
        base_path = Path.cwd()
    node_modules = base_path / "web" / "node_modules"
    if path_exists(node_modules):
        return PreflightCheck(
            name="web", state=PASS, message="web/node_modules existe", action=""
        )
    return PreflightCheck(
        name="web",
        state=FAIL,
        message="web/node_modules nao encontrado",
        action="Execute 'npm install' em web/",
    )


def _check_service(name: str, url: str, action_msg: str, timeout: float = 2.0) -> PreflightCheck:
    try:
        resp = httpx.get(url, timeout=timeout)
        if resp.status_code < 500:
            return PreflightCheck(
                name=name,
                state=WARN,
                message=f"{name} respondeu {resp.status_code}",
                action="",
            )
        return PreflightCheck(
            name=name,
            state=WARN,
            message=f"{name} respondeu {resp.status_code}",
            action=action_msg,
        )
    except Exception as exc:
        return PreflightCheck(
            name=name,
            state=WARN,
            message=f"{name} indisponivel: {exc}",
            action=action_msg,
        )


def check_preflight(
    settings: Settings,
    runner=subprocess.run,
    which=shutil.which,
    path_exists=Path.exists,
) -> PreflightReport:
    checks: list[PreflightCheck] = []

    checks.append(_check_python(runner=runner))
    checks.append(_check_node(runner=runner))
    checks.append(_check_uv(which=which))
    checks.append(_check_ffmpeg(which=which))
    checks.append(_check_tts(settings, path_exists=path_exists))
    checks.append(_check_web(path_exists=path_exists))

    # External services — warn, never fail
    checks.append(
        _check_service(
            "research",
            f"{settings.acervo_url}/health",
            "Inicie research em C:\\dev\\research",
        )
    )
    checks.append(
        _check_service(
            "lm_studio",
            f"{settings.lm_studio_base_url}/models",
            "Inicie LM Studio e carregue um modelo",
        )
    )
    checks.append(
        _check_service(
            "comfyui",
            f"{settings.comfy_url}/system_stats",
            "Inicie ComfyUI",
        )
    )

    return PreflightReport(checks=checks)
