import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, SettingsConfigDict

from forge.domain.operacao import StageName
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Provider = Literal["anthropic", "lm-studio", "openai", "codex", "claude"]

MODELO_PADRAO: dict[str, str] = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5-nano",
    "lm-studio": "google/gemma-4-e4b",
    "codex": "gpt-6.1-sol",
    # Assinatura Claude via `claude -p`; "anthropic" é a API por chave.
    "claude": "claude-opus-5-5",
}

# Nome do GGUF que o audio-generate baixa em `runtime/models`.
MODELO_TTS_PADRAO = "higgs-audio-v3-tts-4b-q8_0.gguf"

# LM Studio ignora o valor, mas o cliente OpenAI exige algo não-vazio.
CHAVE_LOCAL = "lm-studio"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        env_nested_delimiter="__",
    )

    api_key: str | None = None
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FORGE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FORGE_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    model: str | None = None
    effort: str = "high"
    output_dir: Path = Path("output/roteiros")
    studio_runs_dir: Path = Path("output/runs")
    studio_db_path: Path = Path("data/forge.db")
    studio_public_origin: str = "http://127.0.0.1:3100"
    studio_google_client_id: str = ""
    studio_google_client_secret: SecretStr = SecretStr("")

    @field_validator("studio_public_origin")
    @classmethod
    def validar_origem_studio(cls, valor: str) -> str:
        origem = urlsplit(valor)
        local = origem.hostname in {"localhost", "127.0.0.1", "::1"}
        if (not origem.hostname or origem.username is not None or origem.password is not None
                or origem.query or origem.fragment or origem.path not in {"", "/"}
                or not (origem.scheme == "https" or origem.scheme == "http" and local)):
            raise ValueError("Origem do Studio requer HTTPS ou HTTP em loopback")
        return valor.rstrip("/")
    worker_lease_seconds: int = Field(default=15, gt=0)
    worker_heartbeat_seconds: int = Field(default=5, gt=0)
    log_level: str = "INFO"
    max_review_rounds: int = 8
    max_passos: int = 20
    # Multiplicador do prazo por etapa. Existe para modelo local mais lento que
    # o gemma-4-e4b, sem precisar editar a tabela em `stage_timeout`.
    local_stage_timeout_multiplier: float = Field(default=1.0, gt=0)
    # gt=0: propor_beats divide por este valor para estimar quantas imagens
    # uma seção comporta. Um 0 configurado chegaria como ZeroDivisionError lá
    # dentro; melhor a validação recusar o valor aqui, na borda da config.
    midia_alvo_segundos: int = Field(default=15, gt=0)
    # Linha na descrição do vídeo avisando que narração e imagens são geradas
    # por IA. Ligada por padrão: transparência custa uma linha e protege o
    # canal na política de conteúdo sintético do YouTube.
    aviso_ia: bool = True
    # Acabamento do vídeo. A trilha vem de uma pasta do usuário porque música
    # precisa de licença para monetizar; o pipeline não baixa nem gera faixa.
    # Pasta vazia não é erro: o vídeo sai só com a narração.
    trilhas_dir: Path = Path("library/trilhas")
    # Volume-base da trilha antes do ducking. Negativo: é atenuação.
    trilha_volume_db: float = Field(default=-20.0, le=0)
    crossfade_segundos: float = Field(default=0.6, ge=0)
    # Nome de família para o libass (cartões) e arquivo para o Pillow
    # (thumbnail): as duas bibliotecas localizam fonte de jeitos diferentes.
    fonte_video: str = "Georgia"
    fonte_thumbnail: Path = Path(r"C:\Windows\Fonts\georgiab.ttf")

    provider: Provider = "anthropic"
    # Revisor de outro provider. Modelo que revisa o próprio texto tende a
    # aprová-lo; vazio (ou igual a `provider`) mantém um modelo só.
    # `review_model` vazio = padrão do provider revisor — `FORGE_MODEL` é do
    # escritor e não vale para ele.
    review_provider: Provider | None = None
    review_model: str | None = None
    lm_studio_base_url: str = "http://localhost:1234/v1"
    # Nativo: HTTP/OAuth próprio, sem Hermes nem CLI em execução.
    codex_transport: Literal["native", "cli"] = "native"
    codex_auth_file: Path = Field(default_factory=lambda: Path.home() / ".forge" / "codex" / "auth.json")
    codex_image_model: Literal["gpt-image-2"] = "gpt-image-2"
    codex_image_quality: Literal["low", "medium", "high"] = "medium"
    # Compatibilidade explícita com o transporte CLI anterior.
    codex_bin: str = "codex"
    codex_model: str = "gpt-6-astra"
    codex_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    codex_runs_dir: Path = Path("output/codex")
    # Publicação no YouTube: cliente OAuth desktop do próprio usuário (JSON do
    # Google Cloud) e o token do `forge auth youtube login`. O vídeo sobe
    # sempre privado ou agendado; liberar é do dono do canal.
    youtube_client_secrets: Path = Field(
        default_factory=lambda: Path.home() / ".forge" / "youtube" / "client_secret.json")
    # Um token por canal (o Google fixa o canal na tela de login) e
    # `canais.json` com nome, foto e o canal padrão.
    youtube_canais_dir: Path = Field(
        default_factory=lambda: Path.home() / ".forge" / "youtube" / "canais")
    youtube_categoria: str = "27"  # Educação
    # Voz e imagens são geradas: declarar é a escolha conservadora.
    youtube_sintetico: bool = True
    # Assinatura Claude: só pelo `claude -p` oficial. O token OAuth do login
    # não pode ser usado fora das ferramentas da Anthropic — ver
    # services/claude_cli.py.
    claude_bin: str = "claude"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    # Fora do repositório: o CLI sobe de diretório procurando CLAUDE.md e
    # `.claude/`, e o CLAUDE.md daqui manda responder em estilo telegráfico.
    # `--safe-mode` já desliga isso; o diretório fora é a segunda trava.
    claude_runs_dir: Path = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "forge-claude"
    )

    # Serviço externo de pesquisa. Substitui a busca web por completo — ver
    # services/acervo.py.
    acervo_url: str = "http://127.0.0.1:8000"
    acervo_top: int = 8
    acervo_timeout: float = 30.0
    research_min_sources: int = Field(default=3, gt=0)
    # O juiz custa uma chamada de LLM por passagem de pesquisa (~3 min nesta
    # máquina). Desligar troca a detecção de lacuna por velocidade.
    juiz_relevancia: bool = True

    # Realimentação do acervo. O primeiro arquivo é DELE: guarda só a pergunta,
    # uma por linha, sem duplicata, e o próprio acervo o lê de volta
    # (ver unanswered_log.py no projeto research). A evidência completa vai no
    # segundo, que é nosso e ninguém lê de volta. `None` desliga.
    gaps_file: Path | None = Path(r"C:\dev\research\dados\unanswered_questions.txt")
    respostas_ruins_file: Path | None = Path(r"C:\dev\research\dados\respostas_ruins.jsonl")

    # Gerência da GPU. Ver gpu/broker.py: um recurso residente por vez.
    gpu_lock_timeout: float = 900.0
    # `cpu` faz a narração não disputar o slot, liberando-a para rodar
    # concorrente com a fase de imagem.
    studio_api_port: int = Field(default=8765, ge=1, le=65535)
    studio_sse_poll_seconds: float = Field(default=0.25, gt=0)
    studio_sse_keepalive_seconds: float = Field(default=15.0, gt=0)
    studio_worker_poll_seconds: float = Field(default=1.0, gt=0)
    tts_backend: Literal["vulkan", "cpu"] = "vulkan"
    # O audiocpp_server exige `family` no config do modelo: é ela que resolve o
    # package-spec do modelo. Ver runtime/bin/model_specs no audio-generate.
    tts_family: str = "higgs_audio_tts"
    audio_generate_dir: Path = Path(r"C:\dev\audio-generate")
    # O audio-generate distribui o runtime em subdiretórios (`runtime/bin`,
    # `runtime/models`) e guarda a referência de voz na raiz do repo. Derivar
    # `<dir>/audio-generate.exe` (a forma plana antiga) resolvia para paths que
    # não existem: o doctor reprovava o TTS e a etapa de áudio não tinha como
    # rodar. `tts_server_binary`, `tts_model` e `tts_voice_reference` continuam
    # sobrepondo qualquer default.
    tts_model: Path | None = None
    tts_voice_reference: Path | None = None
    tts_reference_text: str = (
        "A vida moderna é um exercício de divisão que não começamos deliberadamente."
    )
    tts_seed: int = 42
    # Timeout de cada pedido HTTP ao audiocpp_server (um trecho por pedido).
    tts_item_timeout: float = Field(default=900, gt=0)
    # O audiocpp_server mantém o modelo carregado durante a etapa de áudio: a
    # carga (~8 s na RX 580) é paga uma vez por backend, não por trecho.
    tts_server_binary: Path | None = None
    tts_server_start_timeout: float = Field(default=120, gt=0)
    # Medido em 2026-11-23 (Ryzen 7 5700X, 16 threads lógicas): com 12 threads
    # sintetizando na CPU, a GPU não perdeu velocidade.
    tts_cpu_threads: int = Field(default=12, ge=1)
    tts_sample_rate: int = Field(default=24000, gt=0)
    comfy_url: str = "http://127.0.0.1:8188"
    image_provider: Literal["comfyui", "codex"] = "comfyui"
    # Preset de imagem: Cosmos Interior
    image_width: int = 1024
    image_height: int = 576
    image_steps: int = 14
    image_cfg: float = 3.2
    image_seed: int = 42
    image_library_dir: Path = Path("library/images")
    image_timeout: float = 1800.0
    comfy_dir: Path = Path("data/comfy")
    comfy_python: Path | None = None
    comfy_output_dir: Path = Path("data/comfy/output")
    # Subir o ComfyUI é trabalho do pipeline: o broker o encerra antes do TTS
    # (o processo segura o heap Vulkan) e o áudio roda antes das imagens.
    comfy_auto_start: bool = True
    comfy_boot_timeout: float = Field(default=180.0, gt=0)
    comfy_args: str = "--directml --lowvram --reserve-vram 0.5"
    lora_dir: Path = Path("library/loras")
    # VRAM que precisa estar livre para o ComfyUI aceitar a próxima geração.
    # 6 GB numa placa de 8 GB: o SDXL não entra abaixo disso.
    comfy_vram_livre_min: int = 6_000_000_000
    lms_bin: str = str(Path.home() / ".lmstudio" / "bin" / "lms.exe")
    gpu_liberacao_timeout: float = 60.0
    # Prazo para encerrar a árvore que o launcher configurado do ComfyUI abriu.
    comfy_process_timeout: float = Field(default=60.0, gt=0)
    # Processo grande fora da posse registrada vira diagnóstico, nunca kill amplo.
    gpu_orphan_diagnostic_threshold_mb: int = Field(default=600, gt=0)

    # Chamada de modelo sem prazo pendura o pipeline: no primeiro run real o
    # LM Studio ficou 12 min sem responder e sem erro.
    llm_timeout: float = 600.0
    llm_max_retries: int = 1
    llm_context_length: int = Field(default=16384, gt=0)
    llm_max_tokens: int = Field(default=4000, gt=0)
    llm_max_tokens_ceiling: int = Field(default=16000, gt=0)
    lm_studio_ttl_seconds: int = Field(default=3600, gt=0)

    @model_validator(mode="after")
    def revisor_nao_pode_ser_local(self) -> "Settings":
        # Modelo local revisando exigiria carregar e liberar a VRAM no meio da
        # etapa; broker e LM Studio só tratam o provider principal.
        if self.review_provider == "lm-studio" and self.provider != "lm-studio":
            raise ValueError(
                "review_provider='lm-studio' não é suportado: o revisor precisa ser "
                "um provider que não ocupa a GPU"
            )
        return self

    @model_validator(mode="after")
    def heartbeat_must_precede_lease(self) -> "Settings":
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError(
                "worker_heartbeat_seconds must be less than worker_lease_seconds"
            )
        return self

    @property
    def resolved_tts_server_binary(self) -> Path:
        return (
            self.tts_server_binary
            or self.audio_generate_dir / "runtime" / "bin" / "audiocpp_server.exe"
        )

    @property
    def resolved_tts_model(self) -> Path:
        return (
            self.tts_model
            or self.audio_generate_dir / "runtime" / "models" / MODELO_TTS_PADRAO
        )

    @property
    def resolved_tts_voice_reference(self) -> Path:
        return self.tts_voice_reference or self.audio_generate_dir / "ref.wav"

    @property
    def resolved_comfy_python(self) -> Path:
        return self.comfy_python or self.comfy_dir / "venv" / "Scripts" / "python.exe"

    @property
    def comfy_args_list(self) -> list[str]:
        return [parte for parte in self.comfy_args.split() if parte]

    @property
    def resolved_model(self) -> str:
        """Modelo do provider ativo. `FORGE_MODEL` sobrepõe qualquer provider."""
        return self.model or MODELO_PADRAO[self.provider]

    @property
    def resolved_api_key(self) -> str | None:
        """Chave do provider ativo — nunca a de outro.

        A chave genérica e as específicas são campos distintos de propósito:
        cruzar as duas manda credencial de um provider para o endpoint de
        outro, que chega como 401 opaco em vez de erro de configuração.
        """
        if self.provider in ("codex", "claude"):
            return None
        if self.provider == "lm-studio":
            return CHAVE_LOCAL
        if self.api_key:
            return self.api_key
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }[self.provider]

    def exigir_api_key(self) -> str:
        chave = self.resolved_api_key
        if not chave:
            raise ValueError(
                f"API key ausente para o provider '{self.provider}'. "
                f"Defina FORGE_API_KEY ou FORGE_{self.provider.upper().replace('-', '_')}_API_KEY."
            )
        return chave

    def stage_timeout(self, stage: "StageName") -> float:
        """Prazo do subprocesso de cada etapa, com o piso do modelo local.

        Os valores-base assumem inferência local (é o provider padrão do
        projeto nesta máquina). Medido: o `gemma-4-e4b` gasta ~700 tokens de
        raciocínio por seção antes da primeira palavra, e a pesquisa sozinha
        passou de 10 min num run real — um teto de 600 s matava a etapa antes
        de ela terminar. `local_stage_timeout_multiplier` cobre modelo mais
        lento sem editar código.
        """
        timeouts = {
            "preparacao": 120,
            "pesquisa": 1800,
            "roteiro": 3600,
            "plano_midia": 1800,
            "audio": 3600,
            "imagens": 3600,
            "montagem": 1800,
            "validacao": 120,
        }
        base = timeouts.get(stage.value, 300)
        return base * self.local_stage_timeout_multiplier  # type: ignore[return-value]

    def secret_values(self) -> list[str]:
        """Return configured credential values for event/error redaction."""
        return list(
            dict.fromkeys(
                value
                for value in (
                    self.api_key,
                    self.anthropic_api_key,
                    self.openai_api_key,
                    self.studio_google_client_secret.get_secret_value(),
                )
                if value
            )
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    logger.info(
        "Settings loaded",
        model=settings.resolved_model,
        provider=settings.provider,
        log_level=settings.log_level,
    )
    return settings
