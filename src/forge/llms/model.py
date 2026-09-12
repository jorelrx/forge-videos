from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


from forge.llms.parsing import _texto


def extract_thinking(resp) -> str:
    """Extrai reasoning_content da resposta do modelo (LM Studio / OpenAI)."""
    content = resp.content
    if isinstance(content, str):
        return ""
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                rc = block.get("reasoning_content")
                if rc and isinstance(rc, str) and rc.strip():
                    return rc
    meta = getattr(resp, "response_metadata", None)
    if meta and isinstance(meta, dict):
        rc = meta.get("reasoning_content")
        if rc and isinstance(rc, str) and rc.strip():
            return rc
    return ""


def invoke_with_thinking(model, messages, *, run_dir=None, etapa="llm", subfase="call"):
    """Wrapper que captura thinking e salva progresso."""
    from forge.services.progresso import ProgressoLogger
    progresso = ProgressoLogger(run_dir) if run_dir else None

    prompt_text = "\n".join(
        f"[{m.role}] {m.content}" for m in messages
    ) if hasattr(messages, '__iter__') and not isinstance(messages, str) else messages

    if progresso:
        progresso.log(etapa, subfase, prompt=prompt_text)

    resp = model.invoke(messages)

    thinking = extract_thinking(resp)
    if progresso and thinking:
        progresso.log(etapa, subfase + "_thinking", thinking=thinking)

    return resp


def build_chat_model(settings: Settings) -> BaseChatModel:
    modelo = settings.resolved_model
    chave = settings.exigir_api_key()
    logger.info("Building LLM model", provider=settings.provider, model=modelo)

    if settings.provider == "lm-studio":
        return ChatOpenAI(
            model=modelo,
            base_url=settings.lm_studio_base_url,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    if settings.provider == "openai":
        return ChatOpenAI(
            model=modelo,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    return ChatAnthropic(
        model=modelo,
        api_key=chave,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
