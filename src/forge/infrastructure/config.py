from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Provider = Literal["anthropic", "lm-studio", "openai"]

MODELO_PADRAO: dict[str, str] = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5-nano",
    "lm-studio": "qwen/qwen3.5-9b",
}

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
    log_level: str = "INFO"
    max_review_rounds: int = 8
    max_passos: int = 20
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
    tts_backend: Literal["vulkan", "cpu"] = "vulkan"
    comfy_url: str = "http://127.0.0.1:8188"
    # VRAM que precisa estar livre para o ComfyUI aceitar a próxima geração.
    # 6 GB numa placa de 8 GB: o SDXL não entra abaixo disso.
    comfy_vram_livre_min: int = 6_000_000_000
    lms_bin: str = str(Path.home() / ".lmstudio" / "bin" / "lms.exe")
    gpu_liberacao_timeout: float = 60.0

    # Chamada de modelo sem prazo pendura o pipeline: no primeiro run real o
    # LM Studio ficou 12 min sem responder e sem erro.
    llm_timeout: float = 600.0
    llm_max_retries: int = 1

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
