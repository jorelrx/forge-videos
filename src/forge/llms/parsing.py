"""Limpeza da saída crua do modelo."""

import re

# Marcador de lista que o modelo insiste em emitir mesmo quando o prompt pede
# uma linha limpa. Mora aqui, e não em `agents/research.py` onde nasceu, porque
# dois agentes precisam remover exatamente a mesma coisa da mesma fonte: o
# parser de queries e o filtro de `verificar` do revisor. Duas cópias
# divergiriam, e a divergência já custou caro uma vez — o filtro que não
# retirava o marcador deixava "1. Sim, o carro volta" passar por alegação.
MARCADOR_LISTA = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _texto(resp) -> str:
    content = resp.content
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content if isinstance(b, dict)
    )
