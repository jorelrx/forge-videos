"""Canais do YouTube conectados e o login disparado pelo painel.

O Google fixa o canal na tela de login ("Escolha uma conta ou canal") e o
token só vale para ele; por isso há um token por canal, em
`<youtube_canais_dir>/<canal_id>.json`, e `canais.json` ao lado com nome,
foto e o padrão. Trocar de canal é conectar outro, nunca reaproveitar token.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from filelock import FileLock

from forge.infrastructure.logging import get_logger
from forge.services.youtube import YouTubeAuthError, YouTubeClient, YouTubeError
from forge.services.youtube_auth import GoogleCredentials

log = get_logger(__name__)

# Ids de canal são "UC" + 22 caracteres; o padrão aceita só o alfabeto deles,
# porque o id vira nome de arquivo.
_ID_CANAL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ClienteAusente(YouTubeAuthError):
    codigo = "youtube_client_missing"


@dataclass(frozen=True)
class Canal:
    id: str
    titulo: str
    thumbnail: str | None
    padrao: bool

    def para_api(self) -> dict:
        return {"id": self.id, "titulo": self.titulo, "thumbnail": self.thumbnail,
                "padrao": self.padrao}


def _gravar_atomico(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, nome = tempfile.mkstemp(prefix=".tmp-", dir=caminho.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as saida:
            saida.write(texto)
        os.replace(nome, caminho)
    finally:
        Path(nome).unlink(missing_ok=True)


def _identificar(credenciais: GoogleCredentials) -> dict:
    return YouTubeClient(credenciais.access_token).meu_canal()


class CanaisYouTube:
    def __init__(self, settings, *, identificar: Callable[[GoogleCredentials], dict] = _identificar):
        self.settings = settings
        self.dir = Path(settings.youtube_canais_dir)
        self._identificar = identificar

    # --- cliente OAuth -------------------------------------------------------

    def cliente_configurado(self) -> bool:
        from forge.services.youtube_auth import ler_cliente
        try:
            ler_cliente(self.settings.youtube_client_secrets)
            return True
        except YouTubeAuthError:
            return False

    def salvar_cliente(self, conteudo: str) -> None:
        """Valida o JSON baixado do Google Cloud antes de gravar."""
        try:
            dados = json.loads(conteudo)
        except ValueError as erro:
            raise YouTubeAuthError("O arquivo não é JSON; envie o JSON baixado do Google Cloud") from erro
        instalado = dados.get("installed") if isinstance(dados, dict) else None
        if not isinstance(instalado, dict):
            raise YouTubeAuthError(
                "Cliente OAuth precisa ser do tipo App para computador (chave 'installed')")
        if not isinstance(instalado.get("client_id"), str) or not instalado["client_id"].strip():
            raise YouTubeAuthError("JSON do cliente sem client_id")
        _gravar_atomico(Path(self.settings.youtube_client_secrets),
                        json.dumps(dados, ensure_ascii=False, indent=2))
        log.info("youtube_cliente_configurado")

    # --- registro de canais ---------------------------------------------------

    def _indice_path(self) -> Path:
        return self.dir / "canais.json"

    def _ler_indice(self) -> dict:
        try:
            dados = json.loads(self._indice_path().read_text(encoding="utf-8"))
            if isinstance(dados, dict) and isinstance(dados.get("canais"), dict):
                return dados
        except (OSError, ValueError):
            pass
        return {"padrao": None, "canais": {}}

    def _gravar_indice(self, indice: dict) -> None:
        _gravar_atomico(self._indice_path(), json.dumps(indice, ensure_ascii=False, indent=2))

    def _trava(self) -> FileLock:
        self.dir.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self._indice_path()) + ".lock", timeout=30)

    def _token_path(self, canal_id: str) -> Path:
        return self.dir / f"{canal_id}.json"

    def listar(self) -> list[Canal]:
        indice = self._ler_indice()
        return [
            Canal(id=cid, titulo=info.get("titulo", ""), thumbnail=info.get("thumbnail"),
                  padrao=cid == indice.get("padrao"))
            for cid, info in sorted(indice["canais"].items(), key=lambda item: item[0])
            if self._token_path(cid).is_file()
        ]

    def padrao(self) -> str | None:
        canais = self.listar()
        return next((c.id for c in canais if c.padrao), canais[0].id if canais else None)

    def _exigir(self, indice: dict, canal_id: str) -> None:
        if canal_id not in indice["canais"] or not self._token_path(canal_id).is_file():
            raise KeyError(canal_id)

    def credenciais(self, canal_id: str) -> GoogleCredentials:
        self._exigir(self._ler_indice(), canal_id)
        return GoogleCredentials(self._token_path(canal_id), self.settings.youtube_client_secrets)

    def titulo(self, canal_id: str) -> str | None:
        info = self._ler_indice()["canais"].get(canal_id)
        return info.get("titulo") if info else None

    def identificar(self, token_temporario: Path) -> Canal:
        credenciais = GoogleCredentials(token_temporario, self.settings.youtube_client_secrets)
        info = self._identificar(credenciais)
        canal_id = str(info.get("id") or "")
        if not _ID_CANAL.fullmatch(canal_id):
            raise YouTubeError("YouTube devolveu um id de canal inesperado")
        return Canal(canal_id, str(info.get("titulo") or canal_id), info.get("thumbnail"), True)

    def registrar(self, token_temporario: Path) -> Canal:
        """Identifica o canal do token recém-obtido e o guarda como padrão."""
        canal = self.identificar(token_temporario)
        canal_id = canal.id
        with self._trava():
            os.replace(token_temporario, self._token_path(canal_id))
            indice = self._ler_indice()
            indice["canais"][canal_id] = {"titulo": canal.titulo, "thumbnail": canal.thumbnail}
            indice["padrao"] = canal_id
            self._gravar_indice(indice)
        log.info("youtube_canal_conectado", canal=canal_id)
        return next(c for c in self.listar() if c.id == canal_id)

    def definir_padrao(self, canal_id: str) -> None:
        with self._trava():
            indice = self._ler_indice()
            self._exigir(indice, canal_id)
            indice["padrao"] = canal_id
            self._gravar_indice(indice)

    def desconectar(self, canal_id: str) -> None:
        """Apaga só o token local; o acesso no Google é revogado pela conta."""
        with self._trava():
            indice = self._ler_indice()
            self._exigir(indice, canal_id)
            self._token_path(canal_id).unlink(missing_ok=True)
            indice["canais"].pop(canal_id, None)
            if indice.get("padrao") == canal_id:
                indice["padrao"] = next(iter(sorted(indice["canais"])), None)
            self._gravar_indice(indice)
        log.info("youtube_canal_desconectado", canal=canal_id)


@dataclass
class EstadoLogin:
    status: Literal["inativo", "aguardando", "concluido", "falhou"] = "inativo"
    url: str | None = None
    erro: str | None = None
    canal_id: str | None = None

    def para_api(self) -> dict:
        return {"status": self.status, "url": self.url, "erro": self.erro,
                "canal_id": self.canal_id}


class LoginGoogle:
    """Login OAuth disparado pelo painel: a API segura o callback em loopback.

    Painel e API rodam na mesma máquina, então o navegador do usuário alcança
    o `127.0.0.1:<porta>` aberto aqui. Um login por vez; um segundo clique
    enquanto o primeiro espera devolve a mesma URL.
    """

    PRAZO = 300.0

    def __init__(self, canais: CanaisYouTube, *, fabrica=None):
        self.canais = canais
        self._fabrica = fabrica or (lambda path: GoogleCredentials(
            path, canais.settings.youtube_client_secrets))
        self._estado = EstadoLogin()
        self._trava = threading.Lock()
        self._fim = threading.Event()
        self._fim.set()

    def estado(self) -> EstadoLogin:
        with self._trava:
            return EstadoLogin(**vars(self._estado))

    def aguardar(self, timeout: float) -> bool:
        return self._fim.wait(timeout)

    def nova_tentativa(self) -> "LoginGoogle":
        return LoginGoogle(self.canais, fabrica=self._fabrica)

    def iniciar(self, *, registrar=None, escopos=None, retorno_studio=None) -> EstadoLogin:
        if not self.canais.cliente_configurado():
            raise ClienteAusente(
                "Cliente OAuth do Google não configurado; envie o JSON do cliente desktop")
        with self._trava:
            if self._estado.status == "aguardando":
                return EstadoLogin(**vars(self._estado))
            self._estado = EstadoLogin(status="aguardando")
            self._fim.clear()
        url_pronta = threading.Event()
        self.canais.dir.mkdir(parents=True, exist_ok=True)
        temporario = self.canais.dir / f".login-{secrets.token_hex(8)}.json"

        def entregar_url(url: str) -> bool:
            with self._trava:
                self._estado.url = url
            url_pronta.set()
            return True

        def alvo():
            try:
                opcoes = {"escopos": escopos} if escopos else {}
                if retorno_studio:
                    opcoes["retorno_studio"] = retorno_studio
                self._fabrica(temporario).login(timeout=self.PRAZO, open_browser=entregar_url, **opcoes)
                canal = (registrar or self.canais.registrar)(temporario)
                with self._trava:
                    self._estado.status, self._estado.canal_id = "concluido", canal.id
                    self._estado.url = None
            except Exception as erro:  # noqa: BLE001 — a thread não tem quem a ouça
                if not isinstance(erro, YouTubeError):
                    log.error("youtube_login_erro_inesperado", tipo=type(erro).__name__)
                with self._trava:
                    self._estado.status = "falhou"
                    self._estado.url = None
                    self._estado.erro = "Login recusado, expirado ou incompatível com o canal."
            finally:
                temporario.unlink(missing_ok=True)
                url_pronta.set()
                self._fim.set()

        threading.Thread(target=alvo, name="forge-youtube-login", daemon=True).start()
        url_pronta.wait(10)
        return self.estado()


@dataclass(frozen=True)
class ContaYouTube:
    """O par que a API serve: canais conectados e o login em curso."""

    canais: CanaisYouTube
    login: LoginGoogle

    @classmethod
    def padrao(cls, settings) -> "ContaYouTube":
        canais = CanaisYouTube(settings)
        return cls(canais=canais, login=LoginGoogle(canais))

    def para_api(self) -> dict:
        return {
            "cliente_configurado": self.canais.cliente_configurado(),
            "canais": [canal.para_api() for canal in self.canais.listar()],
            "login": self.login.estado().para_api(),
        }


__all__ = ["Canal", "CanaisYouTube", "ClienteAusente", "ContaYouTube", "EstadoLogin", "LoginGoogle"]
