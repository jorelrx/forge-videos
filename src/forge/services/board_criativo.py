"""Decisões e geração de ideias do Board da Fase 1."""
from contextlib import nullcontext
from datetime import UTC, datetime

from forge.agents.board_criativo import combinar_ideias, gerar_sugestoes
from forge.domain.board_criativo import CombinarIdeias, GerarSugestoes, PautaManual, Posicionamento
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.logging import get_logger
from forge.llms.model import build_chat_model
from forge.services.board_contexto import perguntas_publicas

log = get_logger(__name__)


def aplicar_comando(board, comando):
    if isinstance(comando, Posicionamento):
        board.posicionamento = comando.texto
        return
    if isinstance(comando, PautaManual):
        if not any(comando.pauta.model_dump().values()):
            raise ValueError("Preencha pelo menos um campo da pauta.")
        board.pauta = comando.pauta
        return

    ideia = board.ideia(comando.ideia_id)
    if comando.acao == "desenvolver":
        board.pauta = ideia.pauta
        board.origem_pauta = ideia
    elif comando.acao == "guardar":
        if all(guardada.id != ideia.id for guardada in board.guardadas):
            board.guardadas.append(ideia.model_copy(deep=True))
    else:
        if all(item.id != ideia.id for item in board.propostas):
            raise ValueError("Só é possível descartar uma proposta da análise atual.")
        board.propostas = [
            item.model_copy(update={"motivo_descarte": comando.motivo}) if item.id == ideia.id else item
            for item in board.propostas
        ]


def preparar_analise(board, pedido, editorial):
    if isinstance(pedido, CombinarIdeias):
        primeiro, segundo = pedido.ideias
        if primeiro == segundo:
            raise ValueError("Selecione duas ideias diferentes.")
        return (board.ideia(primeiro), board.ideia(segundo))
    if board.propostas and not pedido.atualizar:
        return None
    if editorial.aguardando:
        raise ValueError("Aguarde a primeira leitura do histórico.")
    if not editorial.videos and not board.posicionamento:
        raise ValueError("Informe o posicionamento editorial do canal para gerar hipóteses.")
    return board.posicionamento


def executar_analise(repo, dono, pedido, entrada, ctx, editorial, settings, modelo=None):
    try:
        if isinstance(pedido, GerarSugestoes):
            fontes = [*editorial.videos, *editorial.observacoes, *perguntas_publicas(ctx, editorial)]
        else:
            fontes = list({fonte.id: fonte for ideia in entrada for fonte in ideia.referencias
                           if fonte.tipo != "desempenho" or editorial.pode_exibir_analytics}.values())
        slot = montar_broker(settings).exclusivo("llm") if not modelo and settings.provider == "lm-studio" else nullcontext()
        with slot:
            model = modelo() if modelo else build_chat_model(settings)
            resultado = (gerar_sugestoes(model, entrada, fontes) if isinstance(pedido, GerarSugestoes)
                         else combinar_ideias(model, entrada, fontes))
    except Exception as erro:
        log.warning("analise_board_falhou", canal=ctx.canal, operacao=pedido.tipo, erro=type(erro).__name__)

        def falhou(board):
            board.erro = "analise_indisponivel"

        repo.concluir(dono, falhou)
        return

    def aplicar(board):
        if isinstance(pedido, GerarSugestoes):
            board.propostas = resultado
            board.analisado_em = datetime.now(UTC).isoformat()
        else:
            board.candidata = resultado
        board.erro = None

    repo.concluir(dono, aplicar)


def expor_board(board, operacao, editorial):
    dados = board.model_dump()
    if not editorial.pode_exibir_analytics:
        ideias = [*dados["propostas"], *dados["guardadas"], dados["candidata"], dados["origem_pauta"]]
        for ideia in ideias:
            if ideia and any(fonte["tipo"] == "desempenho" for fonte in ideia["referencias"]):
                ideia["referencias"] = [fonte for fonte in ideia["referencias"] if fonte["tipo"] != "desempenho"]
                ideia["justificativa"] = "A justificativa usa indicadores que precisam de nova autorização."
                ideia["hipotese"] = True
    return {**dados, "operacao": operacao, "contexto": editorial.para_api()}
