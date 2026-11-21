import json
import re
from datetime import datetime
from pathlib import Path
from tempfile import mkdtemp

from forge.domain.models import SECOES_NOMES, Fonte, Roteiro, Secao
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.storage import _slug
from forge.services.persistencia import gravar_modelo

logger = get_logger(__name__)

ORDEM = ["tema", "research", "plan", "write", "review"]
_POR_RODADA = {"write", "review"}


def criar_run_dir(settings: Settings, tema: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = settings.output_dir.parent / "runs" / f"{ts}-{_slug(tema)}"
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError:
        run_dir = Path(mkdtemp(prefix=f"{run_dir.name}-", dir=run_dir.parent))
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
    dados = [
        {
            "titulo": f.titulo,
            "autor": f.autor,
            "url": f.url,
            "path": f.path,
            "book_id": f.book_id,
        }
        for f in fontes
    ]
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
        # O eixo vai no frontmatter, não como bloco `## Eixo`: um parser antigo
        # que só conhece Tese e Esboço engoliria o bloco novo dentro do Esboço.
        eixo = resultado.get("eixo")
        linha_eixo = f"eixo: {eixo}\n" if eixo else ""
        return (
            f"---\nagente: plan\n{linha_eixo}---\n\n## Tese\n\n{resultado['tese']}\n\n"
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
    if agente == "write":
        roteiro = resultado.get("roteiro")
        if isinstance(roteiro, Roteiro):
            gravar_modelo(path.with_suffix(".json"), roteiro)
    if agente == "research" and resultado.get("research_passages") is not None:
        # As passagens acumuladas, texto incluso. `fontes` não basta para o
        # --retomar: perde o texto e junta autores por vírgula ("Steiner,
        # Rudolf"). Sem elas o write da retomada escreve sem acervo.
        _passagens_path(path).write_text(json.dumps(
            [_dump(p) for p in resultado["research_passages"]],
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
    logger.debug("Artifact written", agente=agente, path=str(path))
    return path


def _passagens_path(research: Path) -> Path:
    return research.with_suffix(".passages.json")


def _dump(passagem) -> dict:
    return passagem.model_dump() if hasattr(passagem, "model_dump") else dict(passagem)


def _ler_passagens(research: Path) -> list | None:
    origem = _passagens_path(research)
    if not origem.is_file():
        return None
    # Import tardio: o agente de pesquisa depende dos serviços, não o contrário.
    from forge.agents.research import PassageEvidence

    return [
        PassageEvidence.model_validate(item)
        for item in json.loads(origem.read_text(encoding="utf-8"))
    ]


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


def ler_eixo(texto: str) -> str | None:
    """Eixo gravado no frontmatter do plano; `None` em runs anteriores ao eixo."""
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return None
    for linha in partes[1].splitlines():
        if linha.startswith("eixo:"):
            return linha.removeprefix("eixo:").strip() or None
    return None


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
            passagens = _ler_passagens(path)
            if passagens is not None:
                conteudo["research_passages"] = passagens
        elif agente == "plan":
            secoes = _parse_blocos(_corpo(texto), {"Tese", "Esboço"})
            conteudo["tese"] = secoes.get("Tese", "")
            conteudo["esboco"] = secoes.get("Esboço", "")
            conteudo["eixo"] = ler_eixo(texto)
        elif agente == "write":
            estruturado = path.with_suffix(".json")
            if estruturado.is_file():
                salvo = Roteiro.model_validate_json(estruturado.read_text(encoding="utf-8"))
                conteudo["roteiro"] = salvo.model_copy(update={
                    "tema": conteudo.get("tema", salvo.tema),
                    "tese": conteudo.get("tese", salvo.tese),
                })
            else:
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
