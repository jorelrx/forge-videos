import json
import re
from datetime import datetime
from pathlib import Path

from forge.domain.models import SECOES_NOMES, Fonte, Roteiro, Secao
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.storage import _slug

logger = get_logger(__name__)

ORDEM = ["tema", "research", "plan", "write", "review"]
_POR_RODADA = {"write", "review"}


def criar_run_dir(settings: Settings, tema: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = settings.output_dir.parent / "runs" / f"{ts}-{_slug(tema)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run directory created", run_dir=str(run_dir))
    return run_dir


def _nome_arquivo(run_dir: Path, agente: str) -> str:
    """Numera pela contagem de arquivos já presentes, não por `rounds`.

    `rounds` só é incrementado em node_review, então o primeiro e o segundo
    `write` chegariam aqui ambos valendo r1 e o rascunho inicial seria
    sobrescrito. Contar o que já existe no diretório é independente de
    qualquer contador do state e continua correto numa retomada.
    """
    indice = ORDEM.index(agente)
    if agente not in _POR_RODADA:
        return f"{indice:02d}-{agente}.md"
    n = len(list(run_dir.glob(f"{indice:02d}-{agente}-r*.md"))) + 1
    return f"{indice:02d}-{agente}-r{n}.md"


def _fmt_fontes(fontes: list[Fonte]) -> str:
    """Serializa as fontes como JSON — que é YAML válido e round-trip exato.

    Emitir os campos como YAML solto quebra em título com dois-pontos
    ("A Ética: Uma Introdução"), que é a forma comum de título de livro.
    """
    dados = [{"titulo": f.titulo, "autor": f.autor, "url": f.url} for f in fontes]
    return "fontes: " + json.dumps(dados, ensure_ascii=False)


def _render(agente: str, resultado: dict) -> str:
    if agente == "tema":
        return f"---\nagente: tema\n---\n\n{resultado['tema']}\n"

    if agente == "research":
        return (
            "---\nagente: research\n"
            + _fmt_fontes(resultado.get("fontes", []))
            + "\n---\n\n## Brief\n\n"
            + resultado["research_notes"]
            + "\n"
        )

    if agente == "plan":
        return (
            f"---\nagente: plan\n---\n\n## Tese\n\n{resultado['tese']}\n\n"
            f"## Esboço\n\n{resultado['esboco']}\n"
        )

    if agente == "write":
        roteiro = resultado["roteiro"]
        partes = [f"---\nagente: write\ntese: {roteiro.tese}\n---\n"]
        for s in roteiro.secoes:
            partes.append(f"## {s.nome}\n\n{s.conteudo}\n")
        return "\n".join(partes)

    if agente == "review":
        review = resultado["review"]
        partes = [
            f"---\nagente: review\naprovado: {review.aprovado}\n---\n",
            "## Notas\n",
        ]
        for n in review.notas:
            partes.append(f"- [{n.dimensao}] {n.problema} → {n.sugestao}")
        if review.verificar:
            partes.append("\n## Verificar\n")
            for v in review.verificar:
                partes.append(f"- {v}")
        return "\n".join(partes) + "\n"

    raise ValueError(f"agente sem renderizador: {agente}")


def gravar_artefato(run_dir: Path, agente: str, resultado: dict) -> Path:
    path = run_dir / _nome_arquivo(run_dir, agente)
    path.write_text(_render(agente, resultado), encoding="utf-8")
    logger.debug("Artifact written", agente=agente, path=str(path))
    return path


def gravar_bruto(run_dir: Path, agente: str, bruto: str) -> Path:
    indice = ORDEM.index(agente)
    path = run_dir / f"{indice:02d}-{agente}.raw.md"
    path.write_text(bruto, encoding="utf-8")
    logger.debug("Raw artifact written", agente=agente, path=str(path))
    return path


_SECAO_MD = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


def _corpo(texto: str) -> str:
    partes = texto.split("---", 2)
    return partes[2].strip() if len(partes) >= 3 else texto.strip()


def _ler_fontes(texto: str) -> list[Fonte]:
    """Contraparte exata de `_fmt_fontes`: uma linha `fontes: ` + JSON.

    Usa índice, não identidade de objeto, para reconhecer a primeira linha:
    `texto.splitlines()` chamado de novo a cada iteração devolve strings
    novas, então `linha is not texto.splitlines()[0]` é sempre verdadeiro —
    inclusive na própria primeira linha — e a busca abortaria antes de
    alcançar `fontes: `.
    """
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if linha.startswith("fontes: "):
            dados = json.loads(linha.removeprefix("fontes: "))
            return [Fonte(**d) for d in dados]
        if linha.startswith("---") and i != 0:
            break
    return []


def _ultimo(run_dir: Path, agente: str) -> Path | None:
    """Última passagem do agente, por número de rodada — não por ordem alfabética.

    `sorted()` puro colocaria `-r10` antes de `-r2`. A partir de dez rodadas
    isso devolveria o artefato errado silenciosamente.
    """
    indice = ORDEM.index(agente)
    achados = [
        p for p in run_dir.glob(f"{indice:02d}-{agente}*.md")
        if not p.name.endswith(".raw.md")
    ]
    if not achados:
        return None

    def _rodada(p: Path) -> int:
        m = re.search(r"-r(\d+)\.md$", p.name)
        return int(m.group(1)) if m else 0

    return max(achados, key=_rodada)


def carregar_run(run_dir: Path) -> tuple[dict, str]:
    """Reconstrói os campos de conteúdo e devolve o primeiro estágio pendente."""
    conteudo: dict = {}
    for agente in ORDEM:
        path = _ultimo(run_dir, agente)
        if path is None:
            return conteudo, agente
        texto = path.read_text(encoding="utf-8")
        if agente == "tema":
            conteudo["tema"] = _corpo(texto)
        elif agente == "research":
            conteudo["research_notes"] = _corpo(texto).removeprefix("## Brief").strip()
            conteudo["fontes"] = _ler_fontes(texto)
        elif agente == "plan":
            secoes = _parse_blocos(_corpo(texto), {"Tese", "Esboço"})
            conteudo["tese"] = secoes.get("Tese", "")
            conteudo["esboco"] = secoes.get("Esboço", "")
        elif agente == "write":
            secoes = _parse_blocos(_corpo(texto), set(SECOES_NOMES))
            conteudo["roteiro"] = Roteiro(
                tema=conteudo.get("tema", ""),
                tese=conteudo.get("tese", ""),
                secoes=[Secao(nome=k, conteudo=v) for k, v in secoes.items()],
                fontes=conteudo.get("fontes", []),
            )
    return conteudo, "review"


def _parse_blocos(corpo: str, validos: set[str]) -> dict[str, str]:
    """Fatia por `## Nome`, mas só quando `Nome` está em `validos`.

    Sem essa restrição, um `## ` dentro da prosa gerada pelo modelo abriria
    uma seção fantasma e truncaria a real — silenciosamente, na retomada.
    Os nomes de seção do roteiro são um conjunto fechado (`SECOES_NOMES`),
    então usar isso é mais seguro que escapar caractere na escrita.
    """
    marcas = [m for m in _SECAO_MD.finditer(corpo) if m.group(1) in validos]
    blocos: dict[str, str] = {}
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(corpo)
        blocos[m.group(1)] = corpo[m.end():fim].strip()
    return blocos
