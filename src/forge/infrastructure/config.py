from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Provider = Literal["anthropic", "lm-studio", "openai"]


class KnowledgeSettings(BaseModel):
    """Config da camada de conhecimento (RAG V2).

    Stores externos (Qdrant/Neo4j/Postgres) sobem via docker-compose; os
    defaults apontam para localhost, as portas padrão de cada imagem.
    Override por env com o delimitador aninhado, ex:
    `FORGE_KNOWLEDGE__QDRANT_URL=...`.
    """

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "forge_chunks"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "forge-neo4j"

    postgres_dsn: str = "postgresql://forge:forge@localhost:5432/forge"

    # Embeddings via sentence-transformers na CPU, modelo local. Modelo e
    # dimensão têm que casar — ver embed.py.
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch: int = 32

    ocr_enabled: bool = False
    # Parágrafo abaixo disso é mesclado no seguinte: índice, número de página
    # solto e artefato de EPUB não merecem chunk próprio.
    paragrafo_min_chars: int = 40

    # Aquisição de fontes remotas
    remote_top_n: int = 3
    remote_rate_delay: float = 1.0
    remote_timeout: float = 30.0
    wikisource_langs: list[str] = ["pt", "en"]
    cache_dir: str = "output/knowledge_cache"
    # Teto de páginas percorridas por fonte ao paginar/pular já-ingeridos
    # (evita varredura infinita quando a fonte não pagina de verdade).
    remote_max_pages: int = 10

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

    provider: Provider = "anthropic"
    lm_studio_base_url: str = "http://localhost:1234/v1"

    # Inerte durante K1-K4: a ponte com o fluxo de roteiro foi removida (retriever
    # dormente até K5, quando o retrieval volta a ler esta flag).
    knowledge_enabled: bool = False
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)

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
