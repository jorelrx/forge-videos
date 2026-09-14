from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forge.domain.operacao import StageName
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Provider = Literal["anthropic", "lm-studio", "openai"]

MODELO_PADRAO: dict[str, str] = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5-nano",
    "lm-studio": "google/gemma-4-e4b",
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

    provider: Provider = "anthropic"
    lm_studio_base_url: str = "http://localhost:1234/v1"

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
    # O audiocpp_cli exige --family além de --task: é ela que resolve o
    # package-spec do modelo. Ver runtime/bin/model_specs no audio-generate.
    tts_family: str = "higgs_audio_tts"
    audio_generate_dir: Path = Path(r"C:\dev\audio-generate")
    # O audio-generate distribui o runtime em subdiretórios (`runtime/bin`,
    # `runtime/models`) e guarda a referência de voz na raiz do repo. Derivar
    # `<dir>/audio-generate.exe` (a forma plana antiga) resolvia para paths que
    # não existem: o doctor reprovava o TTS e a etapa de áudio não tinha como
    # rodar. `tts_binary`, `tts_model` e `tts_voice_reference` continuam
    # sobrepondo qualquer default.
    tts_binary: Path | None = None
    tts_model: Path | None = None
    tts_voice_reference: Path | None = None
    tts_seed: int = 42
    tts_batch_size: int = Field(default=3, ge=1, le=8)
    tts_item_timeout: float = Field(default=900, gt=0)
    tts_batch_timeout: float = Field(default=3600, gt=0)
    tts_sample_rate: int = Field(default=24000, gt=0)
    comfy_url: str = "http://127.0.0.1:8188"
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
    def heartbeat_must_precede_lease(self) -> "Settings":
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError(
                "worker_heartbeat_seconds must be less than worker_lease_seconds"
            )
        return self

    @property
    def resolved_tts_binary(self) -> Path:
        return self.tts_binary or self.audio_generate_dir / "runtime" / "bin" / "audiocpp_cli.exe"

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
