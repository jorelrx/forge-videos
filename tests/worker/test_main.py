"""Worker CLI and run_loop tests."""
from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.infrastructure.config import Settings
from forge.worker.__main__ import main, run_loop


def _settings(tmp_path: Path) -> Settings:
    audio = tmp_path / "audio"
    audio.mkdir()
    return Settings(
        _env_file=None,
        audio_generate_dir=audio,
        tts_server_binary=audio / "bin.exe",
        tts_model=audio / "model.gguf",
        tts_voice_reference=audio / "voice.wav",
        studio_db_path=tmp_path / "data" / "forge.db",
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "respostas.jsonl",
        studio_worker_poll_seconds=0.01,
    )


class TestRunLoop:
    def test_run_loop_runs_until_stopped(self) -> None:
        worker = MagicMock()
        stopped = MagicMock()
        stopped.is_set.side_effect = [False, False, False, True]

        run_loop(worker, poll_seconds=0.001, stopped=stopped)
        assert worker.run_once.call_count == 3

    def test_run_loop_stops_immediately_when_already_stopped(self) -> None:
        worker = MagicMock()
        stopped = MagicMock()
        stopped.is_set.return_value = True

        run_loop(worker, poll_seconds=0.001, stopped=stopped)
        worker.run_once.assert_not_called()

    def test_run_loop_calls_wait_with_poll_seconds(self) -> None:
        worker = MagicMock()
        worker.run_once.return_value = None
        stopped = MagicMock()
        stopped.is_set.side_effect = [False, False, True]

        run_loop(worker, poll_seconds=0.42, stopped=stopped)
        stopped.wait.assert_called_with(0.42)


class TestWorkerCLI:
    def test_main_with_once_returns_0_even_if_no_run(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mock_worker = MagicMock()
        mock_worker.run_once.return_value = None

        with patch("forge.worker.__main__.build_worker", return_value=mock_worker), \
             patch("forge.worker.__main__.get_settings", return_value=s):
            exit_code = main(["--once"])

        assert exit_code == 0
        mock_worker.run_once.assert_called_once()

    def test_main_passes_worker_id_to_build_worker(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mock_worker = MagicMock()
        mock_worker.run_once.return_value = None

        with patch("forge.worker.__main__.build_worker", return_value=mock_worker) as mock_build, \
             patch("forge.worker.__main__.get_settings", return_value=s):
            exit_code = main(["--once", "--worker-id", "my-worker-123"])

        assert exit_code == 0
        mock_build.assert_called_once_with(s, worker_id="my-worker-123")

    def test_main_installs_signal_handlers(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        mock_worker = MagicMock()
        mock_worker.run_once.return_value = None

        signal_calls: list = []

        def fake_signal(sig, handler):
            signal_calls.append((sig, handler))

        with patch("forge.worker.__main__.signal.signal", side_effect=fake_signal), \
             patch("forge.worker.__main__.build_worker", return_value=mock_worker), \
             patch("forge.worker.__main__.get_settings", return_value=s):
            exit_code = main(["--once"])

        assert exit_code == 0
        sigs = [call[0] for call in signal_calls]
        assert signal.SIGINT in sigs
        assert signal.SIGTERM in sigs


def test_main_em_laco_mantem_batimento_e_apaga_ao_sair(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    s = s.model_copy(update={"output_dir": tmp_path / "roteiros"})
    batimento = tmp_path / ".worker-batimento.json"
    visto: list[bool] = []

    def laco(worker, poll_seconds, stopped):
        visto.append(batimento.exists())

    with patch("forge.worker.__main__.build_worker", return_value=MagicMock()), \
         patch("forge.worker.__main__.get_settings", return_value=s), \
         patch("forge.worker.__main__.signal.signal"), \
         patch("forge.worker.__main__.run_loop", side_effect=laco):
        assert main([]) == 0

    assert visto == [True]
    assert not batimento.exists()
