from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


from forge.llms.parsing import _texto


def _finish_reason(raw: object) -> str | None:
    metadata = getattr(raw, "response_metadata", None)
    if isinstance(metadata, dict) and metadata.get("finish_reason"):
        return str(metadata["finish_reason"])
    additional = getattr(raw, "additional_kwargs", None)
    if isinstance(additional, dict) and additional.get("finish_reason"):
        return str(additional["finish_reason"])
    if isinstance(raw, dict):
        for key in ("finish_reason", "finishReason"):
            if raw.get(key):
                return str(raw[key])
    return None


def invoke_structured(
    model,
    schema,
    messages,
    *,
    initial_max_tokens: int = 4000,
    ceiling_max_tokens: int = 16000,
):
    """Invoke structured output, retrying only a truncated empty parse.

    A parser error with a normal stop is a model/schema defect and is raised
    immediately.  Blind retries hide those defects and can multiply expensive
    local inference calls.
    """
    budget = initial_max_tokens
    while True:
        bounded = model.bind(max_tokens=budget) if hasattr(model, "bind") else model
        try:
            structured = bounded.with_structured_output(schema, include_raw=True)
        except TypeError:
            # Compatibility with older LangChain adapters and the project's
            # small scripted test model.  Real local models use include_raw.
            structured = bounded.with_structured_output(schema)
        response = structured.invoke(messages)
        if isinstance(response, dict):
            parsed = response.get("parsed")
            raw = response.get("raw")
            parse_error = response.get("parsing_error")
        else:
            parsed = response
            raw = response
            parse_error = None
        thinking = extract_thinking(raw) if raw is not None else ""
        # Preserve the reasoning channel for callers/adapters that expose a
        # run log without ever mixing it into the parsed content.
        if thinking:
            logger.debug("Structured model reasoning captured", chars=len(thinking))
        if parsed is not None:
            return parsed
        if _finish_reason(raw) == "length" and budget < ceiling_max_tokens:
            budget = min(budget * 2, ceiling_max_tokens)
            continue
        if _finish_reason(raw) == "length":
            raise RuntimeError("llm_output_truncated")
        if parse_error is not None:
            raise parse_error
        raise RuntimeError("structured output ausente")


def extract_thinking(resp) -> str:
    """Extrai reasoning_content da resposta do modelo (LM Studio / OpenAI)."""
    if resp is None:
        return ""
    if isinstance(resp, dict):
        content = resp.get("content")
    else:
        content = getattr(resp, "content", None)
    if isinstance(content, str):
        return ""
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                rc = block.get("reasoning_content")
                if rc and isinstance(rc, str) and rc.strip():
                    return rc
    meta = resp.get("response_metadata") if isinstance(resp, dict) else getattr(resp, "response_metadata", None)
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
            max_tokens=settings.llm_max_tokens,
        )

    if settings.provider == "openai":
        return ChatOpenAI(
            model=modelo,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            max_tokens=settings.llm_max_tokens,
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
