import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from forge.executors.codex_images import CodexImageClient
from forge.executors.estilo_visual import COSMOS_INTERIOR
from forge.infrastructure.config import Settings
from forge.services.codex import CodexError


class FakeCLI:
    def __init__(self, source=None, *, success=True):
        self.source = source
        self.success = success
        self.calls = []

    def run(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        destination = Path(kwargs['work_dir']) / 'generated.png'
        if self.source and self.source.exists():
            shutil.copyfile(self.source, destination)
        return SimpleNamespace(text=json.dumps({'generated': self.success, 'image_path': str(destination), 'image_model': None}), work_dir=Path(kwargs['work_dir']))


def test_native_image_is_normalized_and_metadata_has_no_invented_model(tmp_path):
    original = tmp_path / 'source.png'
    Image.new('RGB', (1672, 941), 'navy').save(original)
    cli = FakeCLI(original)
    client = CodexImageClient(Settings(_env_file=None), cli=cli)
    dest = tmp_path / 'video' / 'images' / 'i001.png'
    assert client.generate('um viajante', dest=dest) == dest
    with Image.open(dest) as image:
        assert image.size == (1024, 576)
    assert len(cli.calls) == 1
    assert cli.calls[0][1]['allow_images'] is True
    assert 'um viajante' in cli.calls[0][0]
    metadata = client.artifact_metadata(dest)
    assert metadata['image_provider'] == 'codex'
    assert metadata['image_model'] is None
    assert metadata['seed_applied'] is False
    assert Path(metadata['original_path']).is_file()


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'declined'])
def test_no_artifact_on_invalid_generation(tmp_path, kind):
    source = tmp_path / 'source.png'
    if kind == 'corrupt':
        source.write_text('not an image')
    client = CodexImageClient(Settings(_env_file=None), cli=FakeCLI(source, success=kind != 'declined'))
    dest = tmp_path / 'final.png'
    with pytest.raises(CodexError):
        client.generate('imagem', dest=dest)
    assert not dest.exists()


def test_cache_identity_includes_model_resolution_and_backend(tmp_path):
    a = CodexImageClient(Settings(_env_file=None), cli=FakeCLI())
    b = CodexImageClient(Settings(_env_file=None, codex_model='another'), cli=FakeCLI())
    c = CodexImageClient(Settings(_env_file=None, image_width=1280), cli=FakeCLI())
    keys = {x.cache_key('prompt', 42, COSMOS_INTERIOR, []) for x in (a,b,c)}
    assert len(keys) == 3


def test_resume_reuses_verified_receipt_and_corruption_triggers_new_generation(tmp_path):
    original = tmp_path / 'original.png'
    Image.new('RGB', (160, 90), 'navy').save(original)
    cli = FakeCLI(original)
    settings = Settings(_env_file=None)
    dest = tmp_path / 'final.png'
    first = CodexImageClient(settings, cli=cli)
    first.generate('paisagem', dest=dest)
    second = CodexImageClient(settings, cli=cli)
    second.generate('paisagem', dest=dest)
    assert len(cli.calls) == 1
    assert second.artifact_metadata(dest) == first.artifact_metadata(dest)
    dest.write_text('corrompido')
    second.generate('paisagem', dest=dest)
    assert len(cli.calls) == 2


def test_path_outside_native_output_roots_is_rejected(tmp_path):
    outside = tmp_path / 'unrelated.png'
    Image.new('RGB', (160, 90)).save(outside)
    class UntrustedPath:
        def run(self, prompt, **kwargs):
            return SimpleNamespace(text=json.dumps({'generated':True,'image_path':str(outside),'image_model':None}),work_dir=kwargs['work_dir'])
    client = CodexImageClient(Settings(_env_file=None),cli=UntrustedPath())
    with pytest.raises(CodexError,match='diretórios de geração permitidos'):
        client.generate('prompt',dest=tmp_path/'final.png')
    assert not (tmp_path/'final.png').exists()


def test_native_output_root_is_copied_by_host_without_agent_shell(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_HOME',str(tmp_path/'home'))
    class NativeCLI:
        def run(self, prompt, **kwargs):
            source=tmp_path/'home/generated_images/call/image.png'
            source.parent.mkdir(parents=True)
            Image.new('RGB',(160,90),'navy').save(source)
            return SimpleNamespace(text=json.dumps({'generated':True,'image_path':str(source),'image_model':None}),work_dir=kwargs['work_dir'])
    client=CodexImageClient(Settings(_env_file=None),cli=NativeCLI())
    dest=tmp_path/'final.png'
    client.generate('prompt',dest=dest)
    assert dest.is_file()
    assert Path(client.artifact_metadata(dest)['original_path']).is_file()

