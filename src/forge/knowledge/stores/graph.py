"""Neo4j: knowledge graph de entidades + relacionamentos.

Entidade é MERGE por nome (idempotente); relacionamento vira aresta genérica
`:RELACIONA` com o tipo no atributo, para não gerar tipos de aresta dinâmicos.
`params_documento` é puro e testável sem servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento

logger = get_logger(__name__)

_CYPHER_ENTIDADE = (
    "MERGE (e:Entidade {nome: $nome}) "
    "SET e.tipo = $tipo"
)
_CYPHER_RELACAO = (
    "MATCH (a:Entidade {nome: $origem}), (b:Entidade {nome: $destino}) "
    "MERGE (a)-[r:RELACIONA {tipo: $tipo}]->(b) "
    "SET r.documento_id = $documento_id"
)

def params_documento(doc: Documento) -> tuple[list[dict], list[dict]]:
    entidades = [{"nome": e.nome, "tipo": e.tipo} for e in doc.entidades]
    relacoes = [
        {"origem": r.origem, "destino": r.destino, "tipo": r.tipo, "documento_id": doc.id}
        for r in doc.relacionamentos
    ]
    return entidades, relacoes

class GraphStore:
    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def garantir_schema(self) -> None:
        with self._driver.session() as s:
            s.run(
                "CREATE CONSTRAINT entidade_nome IF NOT EXISTS "
                "FOR (e:Entidade) REQUIRE e.nome IS UNIQUE"
            )
        logger.info("Schema Neo4j garantido")

    def upsert_documento(self, doc: Documento) -> None:
        entidades, relacoes = params_documento(doc)
        with self._driver.session() as s:
            for e in entidades:
                s.run(_CYPHER_ENTIDADE, **e)
            for r in relacoes:
                s.run(_CYPHER_RELACAO, **r)
        logger.info("KG atualizado", doc=doc.id, entidades=len(entidades), relacoes=len(relacoes))

    def contar_entidades(self) -> int:
        with self._driver.session() as s:
            return s.run("MATCH (e:Entidade) RETURN count(e) AS n").single()["n"]

    def close(self) -> None:
        self._driver.close()
