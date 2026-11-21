"""Publicação de uma run aprovada no YouTube, retomável pelo estado em disco.

`<run>/video/publicacao.json` é a verdade: cada passo regrava o arquivo, e
repetir a publicação continua de onde parou — a mesma sessão de upload, nunca
um segundo vídeo. O vídeo sobe sempre privado (ou agendado com `publishAt`);
liberar é do dono do canal no YouTube Studio.

Thumbnail e legenda recusadas não desfazem o upload: viram aviso. Só cota e
sessão Google interrompem, e a retomada refaz apenas o que faltou.
"""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from forge.domain.embalagem import Embalagem
from forge.domain.editorial import AberturaAprovada
from forge.services.persistencia import carregar_modelo
from forge.infrastructure.logging import get_logger
from forge.services.youtube import (
    YouTubeAuthError, YouTubeError, YouTubeQuotaError, YouTubeSessaoExpirada,
)

log = get_logger(__name__)

ANTECEDENCIA_MINIMA = timedelta(minutes=15)
LIMITE_TITULO = 100
IDIOMA = "pt-BR"


class PublicacaoRecusada(YouTubeError):
    """A run ou o pedido não servem para publicar; nada foi enviado."""

    codigo = "publication_refused"


class JaPublicado(YouTubeError):
    codigo = "already_published"


class PublicacaoEmAndamento(YouTubeError):
    codigo = "publication_running"


class CanalDesconhecido(YouTubeError):
    codigo = "youtube_channel_unknown"


Passo = Literal["pendente", "ok", "recusada"]


class EstadoPublicacao(BaseModel):
    etapa: Literal["enviando", "thumbnail", "legenda", "concluida", "falhou"]
    titulo: str
    publicar_em: str | None = None
    upload_uri: str | None = None
    bytes_enviados: int = 0
    total_bytes: int = 0
    video_id: str | None = None
    # A sessão de upload pertence ao token do canal: a retomada usa este.
    canal_id: str | None = None
    canal_titulo: str | None = None
    fluxo_geracao: str | None = None
    abertura_sha256: str | None = None
    thumbnail_sha256: str | None = None
    thumbnail: Passo = "pendente"
    legenda: Passo = "pendente"
    avisos: list[str] = Field(default_factory=list)
    erro: str | None = None
    erro_codigo: str | None = None
    atualizado_em: str = ""

    @property
    def url(self) -> str | None:
        return f"https://studio.youtube.com/video/{self.video_id}/edit" if self.video_id else None

    def para_api(self) -> dict:
        return {**self.model_dump(), "url": self.url}


def _caminho(run_dir: Path) -> Path:
    return Path(run_dir) / "video" / "publicacao.json"


def ler_estado(run_dir: Path) -> EstadoPublicacao | None:
    caminho = _caminho(run_dir)
    if not caminho.is_file():
        return None
    return EstadoPublicacao.model_validate_json(caminho.read_text(encoding="utf-8"))


def _gravar(run_dir: Path, estado: EstadoPublicacao) -> None:
    caminho = _caminho(run_dir)
    estado.atualizado_em = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fd, nome = tempfile.mkstemp(prefix=".publicacao-", dir=caminho.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as saida:
            saida.write(estado.model_dump_json(indent=2))
        os.replace(nome, caminho)
    finally:
        Path(nome).unlink(missing_ok=True)


def _validar_run(run_dir: Path) -> Embalagem:
    video = Path(run_dir) / "video"
    try:
        validacao = json.loads((video / "validation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        validacao = {}
    if validacao.get("approved") is not True:
        raise PublicacaoRecusada("Run sem validação final aprovada; só vídeo pronto é publicado")
    if not (video / "final.mp4").is_file():
        raise PublicacaoRecusada("Run sem video/final.mp4")
    try:
        return Embalagem.model_validate_json((video / "embalagem.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise PublicacaoRecusada("Run sem embalagem válida (video/embalagem.json)") from erro


def _validar_titulo(titulo: str) -> str:
    titulo = titulo.strip()
    if not titulo:
        raise PublicacaoRecusada("Título vazio")
    if len(titulo) > LIMITE_TITULO:
        raise PublicacaoRecusada(f"Título passa de {LIMITE_TITULO} caracteres")
    if "<" in titulo or ">" in titulo:
        raise PublicacaoRecusada("O YouTube não aceita < ou > no título")
    return titulo


def _validar_agenda(quando: datetime | None, agora: datetime) -> str | None:
    if quando is None:
        return None
    if quando.tzinfo is None:
        raise PublicacaoRecusada("Data de agendamento precisa de fuso horário")
    if quando < agora + ANTECEDENCIA_MINIMA:
        raise PublicacaoRecusada("Agendamento precisa estar ao menos 15 minutos no futuro")
    return quando.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def montar_metadados(embalagem: Embalagem, estado: EstadoPublicacao, settings) -> dict:
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": bool(settings.youtube_sintetico),
        "embeddable": True,
        "license": "youtube",
    }
    if estado.publicar_em:
        status["publishAt"] = estado.publicar_em
    return {
        "snippet": {
            "title": estado.titulo,
            "description": embalagem.descricao,
            "tags": list(embalagem.tags),
            "categoryId": settings.youtube_categoria,
            "defaultLanguage": IDIOMA,
            "defaultAudioLanguage": IDIOMA,
        },
        "status": status,
    }


def publicar(run_dir: Path, *, cliente, settings, titulo: str | None,
             publicar_em: datetime | None,
             agora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             ao_progredir: Callable[[EstadoPublicacao], None] | None = None,
             canal_id: str | None = None, canal_titulo: str | None = None) -> EstadoPublicacao:
    run_dir = Path(run_dir)
    trava = FileLock(str(_caminho(run_dir)) + ".lock", timeout=0)
    try:
        trava.acquire()
    except Timeout:
        raise PublicacaoEmAndamento("Publicação desta run já está em andamento") from None
    try:
        return _publicar(run_dir, cliente, settings, titulo, publicar_em, agora(), ao_progredir,
                         canal_id, canal_titulo)
    finally:
        trava.release()


def canal_da_retomada(run_dir: Path) -> str | None:
    """Canal de uma publicação que já começou no YouTube; `None` se nada subiu."""
    estado = ler_estado(run_dir)
    if estado is None or (estado.upload_uri is None and estado.video_id is None):
        return None
    return estado.canal_id


def verificar_pedido(run_dir: Path, *, titulo: str | None, publicar_em: datetime | None,
                     agora: datetime, canal_id: str | None = None,
                     canal_titulo: str | None = None) -> tuple[Embalagem, EstadoPublicacao]:
    """Tudo que recusa a publicação sem tocar a rede. Devolve o estado de partida."""
    embalagem = _validar_run(run_dir)
    estado = ler_estado(run_dir)
    if estado is not None and estado.etapa == "concluida":
        raise JaPublicado(f"Run já publicada: {estado.url}")
    if estado is None or (estado.upload_uri is None and estado.video_id is None):
        # Nada chegou ao YouTube ainda: o pedido novo vale inteiro.
        escolhido = titulo if titulo is not None else (
            embalagem.titulos[0].texto if embalagem.titulos else "")
        estado = EstadoPublicacao(
            etapa="enviando", titulo=_validar_titulo(escolhido),
            publicar_em=_validar_agenda(publicar_em, agora),
            total_bytes=(Path(run_dir) / "video" / "final.mp4").stat().st_size,
            canal_id=canal_id, canal_titulo=canal_titulo,
        )
    return embalagem, estado


def _publicar(run_dir, cliente, settings, titulo, publicar_em, agora, ao_progredir,
              canal_id=None, canal_titulo=None):
    embalagem, estado = verificar_pedido(run_dir, titulo=titulo, publicar_em=publicar_em,
                                         agora=agora, canal_id=canal_id,
                                         canal_titulo=canal_titulo)
    video = run_dir / "video"
    estado.erro = estado.erro_codigo = None

    def salvar():
        _gravar(run_dir, estado)
        if ao_progredir:
            ao_progredir(estado)

    try:
        if estado.video_id is None:
            estado.etapa = "enviando"
            _registrar_versao_editorial(video, estado)
            salvar()
            _enviar_video(cliente, settings, embalagem, estado, video / "final.mp4", salvar)
        estado.etapa = "thumbnail"
        salvar()
        if estado.thumbnail == "pendente":
            estado.thumbnail = _passo_opcional(
                lambda: cliente.definir_thumbnail(estado.video_id, video / "thumbnail.jpg"),
                video / "thumbnail.jpg", "thumbnail_recusada", estado)
            if estado.thumbnail == "ok":
                try:
                    estado.thumbnail_sha256 = hashlib.sha256((video / "thumbnail.jpg").read_bytes()).hexdigest()
                except OSError:
                    estado.thumbnail_sha256 = None
        estado.etapa = "legenda"
        salvar()
        if estado.legenda == "pendente":
            estado.legenda = _passo_opcional(
                lambda: cliente.enviar_legenda(estado.video_id, video / "legendas.srt",
                                               idioma=IDIOMA, nome="Português"),
                video / "legendas.srt", "legenda_recusada", estado)
        estado.etapa = "concluida"
        salvar()
        log.info("publicacao_concluida", run=run_dir.name, video_id=estado.video_id)
        return estado
    except YouTubeError as erro:
        estado.etapa = "falhou"
        estado.erro = str(erro)
        estado.erro_codigo = erro.codigo
        salvar()
        log.warning("publicacao_falhou", run=run_dir.name, codigo=erro.codigo)
        raise


def _registrar_versao_editorial(video: Path, estado: EstadoPublicacao) -> None:
    entrada = video / "input.json"
    if entrada.is_file():
        try:
            fluxo = json.loads(entrada.read_text(encoding="utf-8")).get("fluxo_geracao") or {}
            estado.fluxo_geracao = fluxo.get("id", "padrao")
        except (OSError, ValueError, AttributeError):
            estado.fluxo_geracao = None
    aprovada = video / "abertura-aprovada.json"
    if aprovada.is_file():
        try:
            estado.abertura_sha256 = carregar_modelo(aprovada, AberturaAprovada).previa_sha256
            return
        except (OSError, ValueError):
            estado.abertura_sha256 = None
    roteiro = video / "roteiro.json"
    if roteiro.is_file():
        try:
            secoes = json.loads(roteiro.read_text(encoding="utf-8")).get("secoes", [])
            gancho = next((item.get("conteudo") for item in secoes if item.get("nome") == "Gancho"), None)
            if gancho:
                estado.abertura_sha256 = hashlib.sha256(gancho.encode("utf-8")).hexdigest()
        except (OSError, ValueError, AttributeError, TypeError):
            estado.abertura_sha256 = None


def _enviar_video(cliente, settings, embalagem, estado, arquivo, salvar):
    def avancar(offset: int):
        estado.bytes_enviados = offset
        salvar()

    for tentativa in range(2):
        if estado.upload_uri is None:
            estado.upload_uri = cliente.iniciar_upload(
                montar_metadados(embalagem, estado, settings), estado.total_bytes)
            estado.bytes_enviados = 0
            salvar()
        try:
            recurso = cliente.enviar_arquivo(
                estado.upload_uri, arquivo, inicio=estado.bytes_enviados, ao_avancar=avancar)
            break
        except YouTubeSessaoExpirada:
            if tentativa:
                raise
            estado.upload_uri = None
    video_id = recurso.get("id") if isinstance(recurso, dict) else None
    if not isinstance(video_id, str) or not video_id:
        raise YouTubeError("Upload terminou sem id de vídeo na resposta do YouTube")
    estado.video_id = video_id
    estado.bytes_enviados = estado.total_bytes
    estado.upload_uri = None


def _passo_opcional(acao, arquivo: Path, aviso: str, estado: EstadoPublicacao) -> Passo:
    """Thumbnail e legenda: recusa vira aviso; cota e sessão interrompem."""
    if not arquivo.is_file():
        estado.avisos.append(f"{aviso}: {arquivo.name} ausente")
        return "recusada"
    try:
        acao()
        return "ok"
    except (YouTubeQuotaError, YouTubeAuthError):
        raise
    except YouTubeError as erro:
        estado.avisos.append(f"{aviso}: {erro}")
        return "recusada"


def registrar_falha_inesperada(run_dir: Path, erro: BaseException) -> None:
    """Erro fora do contrato (disco, bug): o estado não pode ficar "enviando"."""
    estado = ler_estado(run_dir)
    if estado is None or estado.etapa == "concluida":
        return
    estado.etapa = "falhou"
    estado.erro = f"Erro inesperado: {type(erro).__name__}: {erro}"
    estado.erro_codigo = "unexpected"
    _gravar(run_dir, estado)


class Publicador:
    """Dispara publicações em segundo plano para o painel, uma por run.

    Upload é rede, não GPU: não passa pelo worker nem vira etapa da run, que já
    terminou. Se a API cair no meio, o estado em disco fica "enviando" sem
    ninguém trabalhando — `em_andamento` diz a diferença, e publicar de novo
    retoma a mesma sessão de upload.
    """

    def __init__(self, settings, *, canais=None, cliente_factory=None,
                 iniciar_thread=None):
        self.settings = settings
        if canais is None:
            from forge.services.youtube_canais import CanaisYouTube
            canais = CanaisYouTube(settings)
        self.canais = canais
        if cliente_factory is None:
            from forge.services.youtube import YouTubeClient
            cliente_factory = lambda credenciais: YouTubeClient(credenciais.access_token)  # noqa: E731
        self._cliente_factory = cliente_factory
        self._iniciar_thread = iniciar_thread or self._thread
        self._ativos: set[str] = set()
        self._trava = threading.Lock()

    @staticmethod
    def _thread(alvo) -> None:
        threading.Thread(target=alvo, name="forge-publicacao", daemon=True).start()

    def conectado(self) -> bool:
        return bool(self.canais.listar())

    def em_andamento(self, run_dir: Path) -> bool:
        with self._trava:
            return str(Path(run_dir).resolve()) in self._ativos

    def iniciar(self, run_dir: Path, *, titulo: str | None, publicar_em: datetime | None,
                canal_id: str | None = None) -> None:
        run_dir = Path(run_dir)
        chave = str(run_dir.resolve())
        with self._trava:
            if chave in self._ativos:
                raise PublicacaoEmAndamento("Publicação desta run já está em andamento")
            verificar_pedido(run_dir, titulo=titulo, publicar_em=publicar_em,
                             agora=datetime.now(timezone.utc))
            if not self.conectado():
                raise YouTubeAuthError(
                    "Nenhum canal do YouTube conectado. Conecte uma conta Google na aba "
                    "Publicação ou rode forge auth youtube login")
            # O que já subiu pertence ao canal gravado; o pedido só vale do zero.
            canal = canal_da_retomada(run_dir) or canal_id or self.canais.padrao()
            try:
                credenciais = self.canais.credenciais(canal)
            except KeyError:
                raise CanalDesconhecido(
                    f"Canal {canal} não está conectado; conecte-o de novo") from None
            canal_titulo = self.canais.titulo(canal)
            self._ativos.add(chave)

        def alvo():
            try:
                publicar(run_dir, cliente=self._cliente_factory(credenciais),
                         settings=self.settings, titulo=titulo, publicar_em=publicar_em,
                         canal_id=canal, canal_titulo=canal_titulo)
            except YouTubeError:
                pass  # já gravado no estado
            except Exception as erro:  # noqa: BLE001 — a thread não tem quem a ouça
                log.exception("publicacao_erro_inesperado", run=run_dir.name)
                registrar_falha_inesperada(run_dir, erro)
            finally:
                with self._trava:
                    self._ativos.discard(chave)

        self._iniciar_thread(alvo)


__all__ = [
    "CanalDesconhecido", "EstadoPublicacao", "JaPublicado", "canal_da_retomada", "PublicacaoEmAndamento", "PublicacaoRecusada",
    "Publicador", "ler_estado", "montar_metadados", "publicar", "verificar_pedido",
]
