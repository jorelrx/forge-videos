"""Safe adapter for the local audio-generate batch command."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Sequence

from forge.domain.execucao import FailureClass, FailureDetail
from forge.infrastructure.config import Settings

_EMOTION_TAG = re.compile(r"<\|emotion:[^|]*\|>")
_MAX_STDERR_BYTES = 4 * 1024


@dataclass(frozen=True, slots=True)
class AudioRequest:
    item_key: str
    text: str
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class AudioOutcome:
    item_key: str
    path: Path | None = None
    failure: FailureDetail | None = None
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.path is not None and self.failure is None

    @classmethod
    def succeeded(cls, item_key: str, path: Path) -> "AudioOutcome":
        return cls(item_key=item_key, path=Path(path))

    @classmethod
    def failed(cls, item_key: str, code: str, message: str) -> "AudioOutcome":
        return cls(
            item_key=item_key,
            failure=FailureDetail(
                code=code,
                message=message,
                failure_class=FailureClass.PROCESS,
                retriable=True,
                recommended_action="Verificar o gerador de áudio e tentar novamente",
                adapter="audio_generate",
                attempt=1,
                item_key=item_key,
            ),
        )


def _stderr_tail(value: object) -> str:
    raw = str(value or "").encode("utf-8", errors="replace")
    return raw[-_MAX_STDERR_BYTES:].decode("utf-8", errors="replace")


def classify_audio_failure(
    stderr: str, *, exit_code: int, item_key: str | None = None, attempt: int = 1
) -> FailureDetail:
    """Classify known audio-generate exits without exposing unbounded stderr."""
    stderr = _stderr_tail(stderr)
    if "reached max_tokens before EOC" in stderr:
        code, failure_class, retriable, action = (
            "tts_max_tokens_before_eoc", FailureClass.DETERMINISTIC, False,
            "Encurtar o bloco de narração antes de gerar novamente",
        )
    elif "ggml_vulkan: Device memory allocation" in stderr:
        code, failure_class, retriable, action = (
            "tts_vulkan_oom", FailureClass.CAPACITY, True,
            "Liberar VRAM ou reduzir o lote de narração",
        )
    else:
        code, failure_class, retriable, action = (
            "tts_process_failed", FailureClass.PROCESS, True,
            "Verificar o gerador de áudio e tentar novamente",
        )
    return FailureDetail(
        code=code,
        message=f"Geração de áudio falhou (exit_code={exit_code})",
        failure_class=failure_class,
        retriable=retriable,
        recommended_action=action,
        adapter="audio_generate",
        attempt=attempt,
        item_key=item_key,
        services={"exit_code": exit_code, "stderr_tail": stderr},
    )


_OUTPUT_MISSING = "tts_output_missing"


def _missing_output(item_key: str, detail: str) -> AudioOutcome:
    """Saída anunciada que não existe é falha determinística, não sucesso."""
    return AudioOutcome(
        item_key=item_key,
        failure=FailureDetail(
            code=_OUTPUT_MISSING,
            message=f"Áudio não produzido: {detail}",
            failure_class=FailureClass.DETERMINISTIC,
            retriable=False,
            recommended_action=(
                "Conferir --out-dir/--batch-manifest-out do audiocpp_cli"
            ),
            adapter="audio_generate",
            attempt=1,
            item_key=item_key,
        ),
    )


def _map_manifest_outputs(
    items: Sequence[AudioRequest], output_dir: Path, manifest_path: Path
) -> list[AudioOutcome]:
    """Traduz o manifesto do batch em resultados por item.

    O binário ignora o `id` do pedido e grava `line_<N>.wav`, devolvendo esse
    nome no manifesto, na ordem das linhas. Sem ler o manifesto, o adaptador
    anunciaria um `<item_key>.wav` que o disco não tem — e um exit 0 com N
    áudios viraria N sucessos falsos.
    """
    try:
        dados = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        entradas = dados.get("requests") or []
    except (OSError, ValueError) as error:
        return [
            _missing_output(item.item_key, f"manifesto ilegível ({error})")
            for item in items
        ]

    outcomes: list[AudioOutcome] = []
    for index, item in enumerate(items):
        if index >= len(entradas):
            outcomes.append(
                _missing_output(item.item_key, "manifesto não cobre todos os itens")
            )
            continue
        nome = str((entradas[index] or {}).get("id") or "")
        caminho = output_dir / f"{nome}.wav"
        if not nome or not caminho.is_file():
            outcomes.append(
                _missing_output(
                    item.item_key, f"arquivo declarado no manifesto ausente: {nome!r}"
                )
            )
            continue
        outcomes.append(AudioOutcome.succeeded(item.item_key, caminho))
    return outcomes


class AudioGenerateClient:
    def __init__(
        self,
        settings: Settings,
        *,
        run: Callable[..., object] | None = None,
    ) -> None:
        self.settings = settings
        self._run = run or subprocess.run

    def build_argv(
        self,
        batch_text_file: Path,
        output_dir: Path,
        *,
        seed: int | None = None,
        manifest_path: Path | None = None,
    ) -> list[str]:
        # Contrato real do audiocpp_cli: `--task` e `--family` são obrigatórios,
        # a referência de voz é `--voice-ref` e a saída é `--out-dir`. As formas
        # antigas (`--voice-reference`, `--output-dir`, sem task/family) fazem o
        # binário sair 1 sem gerar nada.
        argv = [
            str(self.settings.resolved_tts_binary),
            "--task", "tts",
            "--family", self.settings.tts_family,
            "--model", str(self.settings.resolved_tts_model),
            "--backend", self.settings.tts_backend,
            "--voice-ref", str(self.settings.resolved_tts_voice_reference),
            "--batch-text-file", str(batch_text_file),
            "--out-dir", str(output_dir),
            "--seed", str(self.settings.tts_seed if seed is None else seed),
        ]
        if manifest_path is not None:
            argv += ["--batch-manifest-out", str(manifest_path)]
        return argv

    @staticmethod
    def _clean_text(value: str) -> str:
        return _EMOTION_TAG.sub("", value).strip()

    def synthesize_batch(
        self, items: Sequence[AudioRequest], output_dir: Path
    ) -> list[AudioOutcome]:
        if not items:
            return []
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".jsonl", prefix="tts-batch-",
            dir=output_dir, delete=False,
        ) as source:
            for item in items:
                source.write(json.dumps(
                    {"id": item.item_key, "text": self._clean_text(item.text)},
                    ensure_ascii=False,
                ) + "\n")
            batch_text_file = Path(source.name)
        manifest_path = batch_text_file.with_suffix(".manifest.json")
        argv = self.build_argv(
            batch_text_file, output_dir, seed=items[0].seed, manifest_path=manifest_path
        )
        timeout = min(
            self.settings.tts_batch_timeout,
            self.settings.tts_item_timeout * len(items),
        )
        stderr = ""
        exit_code = 1
        try:
            completed = self._run(
                argv,
                cwd=self.settings.audio_generate_dir,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stderr = _stderr_tail(getattr(completed, "stderr", ""))
            exit_code = int(getattr(completed, "returncode", 1))
            if exit_code == 0:
                return _map_manifest_outputs(items, output_dir, manifest_path)
        except (OSError, subprocess.SubprocessError) as error:
            stderr = _stderr_tail(error)
        return [
            AudioOutcome(
                item_key=item.item_key,
                failure=classify_audio_failure(
                    stderr, exit_code=exit_code, item_key=item.item_key
                ),
                stderr=stderr,
            )
            for item in items
        ]


__all__ = [
    "AudioGenerateClient",
    "AudioOutcome",
    "AudioRequest",
    "classify_audio_failure",
]
