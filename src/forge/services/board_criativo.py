"""Decisões, conversa e geração de ideias do Board."""
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4

from forge.agents.board_criativo import combinar_ideias, gerar_sugestoes, responder_conversa
from forge.domain.board_criativo import (
    AplicarSugestao, CombinarIdeias, Conversar, EscolhaFluxo, GerarSugestoes, MensagemBoard, Pauta, PautaManual,
    Posicionamento, RemoverGuardada,
)
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.logging import get_logger
from forge.llms.model import build_chat_model
from forge.repositories.fluxos_geracao import FluxosGeracaoRepository
from forge.services.board_contexto import perguntas_publicas

log = get_logger(__name__)
LIMITE_CONVERSA = 60


def _agora() -> str:
    return datetime.now(UTC).isoformat()


def _manter_conversa(board):
    board.conversa = board.conversa[-LIMITE_CONVERSA:]


def aplicar_comando(board, comando):
    if isinstance(comando, Posicionamento):
        board.posicionamento = comando.texto
        return
    if isinstance(comando, PautaManual):
        if comando.pauta.vazia():
            raise ValueError("Preencha pelo menos um campo da pauta.")
        board.pauta = comando.pauta
        return
    if isinstance(comando, EscolhaFluxo):
        board.fluxo_id = comando.fluxo_id
        return
    if isinstance(comando, RemoverGuardada):
        if all(ideia.id != comando.ideia_id for ideia in board.guardadas):
            raise ValueError("Ideia guardada indisponível.")
        board.guardadas = [ideia for ideia in board.guardadas if ideia.id != comando.ideia_id]
        return
    if isinstance(comando, AplicarSugestao):
        _aplicar_sugestao(board, comando)
        return

    ideia = board.ideia(comando.ideia_id)
    if comando.acao == "desenvolver":
        board.pauta = Pauta(**ideia.pauta.model_dump())
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


def _aplicar_sugestao(board, comando: AplicarSugestao):
    mensagem = board.mensagem(comando.mensagem_id)
    propostas = {alteracao.campo: alteracao.valor for alteracao in mensagem.alteracoes}
    if set(comando.campos) - propostas.keys():
        raise ValueError("A sugestão não propõe todos os campos escolhidos.")
    atual = (board.pauta or Pauta()).model_dump()
    board.pauta = Pauta.model_validate({**atual, **{campo: propostas[campo] for campo in comando.campos}})
    mensagem.aplicadas = sorted({*mensagem.aplicadas, *comando.campos})


def preparar_analise(board, pedido, editorial):
    if isinstance(pedido, Conversar):
        board.conversa.append(MensagemBoard(id=uuid4().hex, autor="criador", texto=pedido.mensagem,
                                            criada_em=_agora()))
        _manter_conversa(board)
        referencias = board.origem_pauta.referencias if board.origem_pauta else []
        return {"pauta": board.pauta or Pauta(), "conversa": list(board.conversa), "base": board.revisao,
                "fontes": [*editorial.videos, *referencias]}
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


def _fontes_permitidas(fontes, editorial):
    return [fonte for fonte in fontes if fonte.tipo != "desempenho" or editorial.pode_exibir_analytics]


def executar_analise(repo, dono, pedido, entrada, ctx, editorial, settings, modelo=None):
    try:
        if isinstance(pedido, GerarSugestoes):
            fontes = [*editorial.videos, *editorial.observacoes, *perguntas_publicas(ctx, editorial)]
        elif isinstance(pedido, Conversar):
            fontes = _fontes_permitidas({f.id: f for f in entrada["fontes"]}.values(), editorial)
        else:
            fontes = _fontes_permitidas({fonte.id: fonte for ideia in entrada for fonte in ideia.referencias}.values(),
                                        editorial)
        slot = montar_broker(settings).exclusivo("llm") if not modelo and settings.provider == "lm-studio" else nullcontext()
        with slot:
            model = modelo() if modelo else build_chat_model(settings)
            if isinstance(pedido, GerarSugestoes):
                resultado = gerar_sugestoes(model, entrada, fontes)
            elif isinstance(pedido, Conversar):
                resultado = responder_conversa(model, entrada["pauta"], entrada["conversa"], fontes)
            else:
                resultado = combinar_ideias(model, entrada, fontes)
    except Exception as erro:
        log.warning("analise_board_falhou", canal=ctx.canal, operacao=pedido.tipo, erro=type(erro).__name__)

        def falhou(board):
            board.erro = "analise_indisponivel"

        repo.concluir(dono, falhou)
        return

    def aplicar(board):
        if isinstance(pedido, GerarSugestoes):
            board.propostas = resultado
            board.analisado_em = _agora()
        elif isinstance(pedido, Conversar):
            texto, alteracoes = resultado
            board.conversa.append(MensagemBoard(id=uuid4().hex, autor="ia", texto=texto, criada_em=_agora(),
                                                base_revisao=entrada["base"], alteracoes=alteracoes))
            _manter_conversa(board)
        else:
            board.candidata = resultado
        board.erro = None

    repo.concluir(dono, aplicar)


def fluxos_compativeis(db, canal) -> list[dict]:
    """Todo fluxo cadastrado passa pela escrita do roteiro e consome a pauta."""
    return [{**fluxo.model_dump(include={"id", "nome", "descricao"}), "disponivel": True, "motivo": None}
            for fluxo in FluxosGeracaoRepository(db).listar(canal_id=canal)]


def validar_fluxo(fluxos, fluxo_id):
    fluxo = next((item for item in fluxos if item["id"] == fluxo_id), None)
    if fluxo is None:
        raise ValueError("Fluxo de geração desconhecido.")
    if not fluxo["disponivel"]:
        raise ValueError(fluxo["motivo"] or "Fluxo indisponível para a pauta.")


def pendencias(board, fluxos) -> list[dict]:
    pauta = board.pauta or Pauta()
    faltas = []
    if not pauta.tema:
        faltas.append({"campo": "tema", "mensagem": "Defina o tema."})
    if not pauta.promessa:
        faltas.append({"campo": "promessa", "mensagem": "Escreva a promessa do episódio."})
    if not pauta.blocos:
        faltas.append({"campo": "blocos", "mensagem": "Inclua pelo menos um bloco."})
    fluxo = next((item for item in fluxos if item["id"] == board.fluxo_id), None)
    if fluxo is None:
        mensagem = "Escolha um fluxo de geração." if any(f["disponivel"] for f in fluxos) else \
            "Nenhum fluxo disponível gera roteiro a partir da pauta."
        faltas.append({"campo": "fluxo", "mensagem": mensagem})
    elif not fluxo["disponivel"]:
        faltas.append({"campo": "fluxo", "mensagem": fluxo["motivo"] or "O fluxo escolhido está indisponível."})
    return faltas


def expor_board(board, operacao, editorial, fluxos):
    dados = board.model_dump()
    if not editorial.pode_exibir_analytics:
        ideias = [*dados["propostas"], *dados["guardadas"], dados["candidata"], dados["origem_pauta"]]
        for ideia in ideias:
            if ideia and any(fonte["tipo"] == "desempenho" for fonte in ideia["referencias"]):
                ideia["referencias"] = [fonte for fonte in ideia["referencias"] if fonte["tipo"] != "desempenho"]
                ideia["justificativa"] = "A justificativa usa indicadores que precisam de nova autorização."
                ideia["hipotese"] = True
    return {**dados, "operacao": operacao, "contexto": editorial.para_api(),
            "fluxos": fluxos, "pendencias": pendencias(board, fluxos)}
