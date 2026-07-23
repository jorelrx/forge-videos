"""Neo4j: knowledge graph de entidades + relacionamentos.

Entidade é MERGE por nome (idempotente); relacionamento vira aresta genérica
`:RELACIONA` com o tipo no atributo, para não gerar tipos de aresta dinâmicos.
`params_documento` é puro e testável sem servidor.
"""
from forge.infrastructure.logging import get_logger

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

def params_documento(
    documento_id: str, entidades: list, relacionamentos: list
) -> tuple[list[dict], list[dict]]:
    """Dormente até K3: o grafo semântico só passa a ser escrito lá.

    Recebe listas explícitas em vez de um Documento — a árvore estrutural não
    carrega entidade nem relação, elas são da camada semântica.
    """
    nos = [{"nome": e.nome, "tipo": e.tipo} for e in entidades]
    arestas = [
        {"origem": r.origem, "destino": r.destino, "tipo": r.tipo,
         "documento_id": documento_id}
        for r in relacionamentos
    ]
    return nos, arestas

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

    def resetar(self) -> None:
        with self._driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
        logger.warning("Grafo Neo4j esvaziado")
        self.garantir_schema()

    def upsert_semantica(
        self, documento_id: str, entidades: list, relacionamentos: list
    ) -> None:
        """Dormente até K3. Nenhum chamador em K1."""
        nos, arestas = params_documento(documento_id, entidades, relacionamentos)
        with self._driver.session() as s:
            for no in nos:
                s.run(_CYPHER_ENTIDADE, **no)
            for aresta in arestas:
                s.run(_CYPHER_RELACAO, **aresta)
        logger.info("KG atualizado", doc=documento_id, entidades=len(nos), relacoes=len(arestas))

    def contar_entidades(self) -> int:
        with self._driver.session() as s:
            return s.run("MATCH (e:Entidade) RETURN count(e) AS n").single()["n"]

    def close(self) -> None:
        self._driver.close()
