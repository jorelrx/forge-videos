from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt


def gerar_tema(model, tema: str | None = None) -> str:
    if tema:
        return tema
    resp = model.invoke([HumanMessage(content=load_prompt("tema"))])
    return _texto(resp).strip()


def _texto(resp) -> str:
    content = resp.content
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content if isinstance(b, dict)
    )
