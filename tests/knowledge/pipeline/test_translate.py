from langchain_core.messages import AIMessage

from forge.knowledge.pipeline.translate import traduzir


class ModeloFixo:
    def __init__(self, resposta):
        self.resposta = resposta

    def invoke(self, mensagens):
        return AIMessage(content=self.resposta)


def test_traduzir_retorna_traducao_do_modelo():
    assert traduzir(ModeloFixo("stoicism"), "estoicismo", "en") == "stoicism"


def test_traduzir_resposta_vazia_cai_para_original():
    assert traduzir(ModeloFixo("   "), "estoicismo", "en") == "estoicismo"


def test_traduzir_falha_do_modelo_cai_para_original():
    class Boom:
        def invoke(self, mensagens):
            raise RuntimeError("api fora")

    assert traduzir(Boom(), "estoicismo", "en") == "estoicismo"
