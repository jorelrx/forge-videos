import re
import unicodedata
from dataclasses import dataclass
from importlib.resources import files

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_SECAO = re.compile(r"^#{2,}\s*(.+?)\s*$", re.MULTILINE)

# Os quatro eixos editoriais do canal Conquistas Cósmicas. Cada um tem um
# arquivo de referência com filósofos, conceitos e — o que mais importa para o
# revisor — as atribuições falsas comuns daquele território.
EIXOS: tuple[str, ...] = (
    "estoicismo", "autoconhecimento", "niilismo-absurdo", "etica-digital-ia",
)
SEM_EIXO = "(sem referência de eixo)"
_FOCO = "Foco do canal neste eixo:"

SECAO_EXCLUSIVA = "procedimento"
SECOES_VALIDAS = {"criterios", "anti-padroes", "procedimento"}


def _chave(titulo: str) -> str:
    """Normaliza título de seção: sem acento, sem pontuação de borda, minúsculo.

    O corte de Procedimento é a fronteira entre o que um agente produtor recebe
    e o que um agente revisor nunca deve ver. Comparação exata falharia em
    silêncio num typo de quem escreve a skill — aqui um título desconhecido
    vira erro alto.
    """
    sem_acento = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    return sem_acento.strip(" :.\t").casefold()


@dataclass(frozen=True)
class Skill:
    nome: str
    dono: str | None
    dominio: bool
    secoes: dict[str, str]


def _parse_frontmatter(bruto: str) -> dict[str, str]:
    dados: dict[str, str] = {}
    for linha in bruto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        dados[chave.strip()] = valor.strip()
    return dados


def _parse_secoes(corpo: str) -> dict[str, str]:
    marcas = list(_SECAO.finditer(corpo))
    secoes: dict[str, str] = {}
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
        secoes[m.group(1)] = corpo[m.end():fim].strip()
    return secoes


def carregar(nome: str) -> Skill:
    texto = (files("forge.skills") / f"{nome}.md").read_text(encoding="utf-8")
    m = _FRONTMATTER.match(texto)
    if m is None:
        raise ValueError(f"skill '{nome}' sem frontmatter")
    meta = _parse_frontmatter(m.group(1))
    dono = meta.get("dono") or None
    return Skill(
        nome=meta.get("nome", nome),
        dono=dono,
        dominio=meta.get("dominio", "false").lower() == "true",
        secoes=_parse_secoes(m.group(2)),
    )


def _referencia(eixo: str) -> str:
    recurso = files("forge.skills") / "conquistas-cosmicas" / "references" / f"{eixo}.md"
    return recurso.read_text(encoding="utf-8")


def carregar_eixo(eixo: str | None) -> str:
    """Referência do eixo, ou um marcador quando não há eixo.

    A referência orienta a escrita e alerta sobre atribuições falsas; não é
    evidência — evidência é só a passagem do acervo. Eixo desconhecido cai no
    marcador em vez de levantar: o eixo vem do modelo, e um valor torto não
    pode derrubar um roteiro que segue válido sem a referência.
    """
    if eixo not in EIXOS:
        return SEM_EIXO
    return _referencia(eixo)


def resumo_eixos() -> str:
    """Uma linha por eixo com o foco declarado na referência."""
    linhas = []
    for eixo in EIXOS:
        foco = next(
            (linha.removeprefix(_FOCO).strip()
             for linha in _referencia(eixo).splitlines() if linha.startswith(_FOCO)),
            "",
        )
        linhas.append(f"- {eixo}: {foco}")
    return "\n".join(linhas)


def load_skills(nomes: list[str], agente: str) -> str:
    if not nomes:
        return "(nenhuma)"
    blocos: list[str] = []
    for nome in nomes:
        skill = carregar(nome)
        partes = [f"# Skill: {skill.nome}"]
        for titulo, corpo in skill.secoes.items():
            chave = _chave(titulo)
            if chave not in SECOES_VALIDAS:
                raise ValueError(
                    f"skill '{nome}': seção {titulo!r} não reconhecida "
                    f"(esperado: Critérios, Anti-padrões ou Procedimento)"
                )
            if chave == SECAO_EXCLUSIVA and skill.dono != agente:
                continue
            partes.append(f"## {titulo}\n{corpo}")
        blocos.append("\n\n".join(partes))
        logger.debug("Skill loaded", skill=nome, agente=agente, dono=skill.dono)
    return "\n\n---\n\n".join(blocos)
