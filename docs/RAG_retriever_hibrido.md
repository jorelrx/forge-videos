> Escopo de K5, depois que K1-K4 tiverem gravado os sinais. Fonte de verdade da
> camada Knowledge: [knowledge.md](knowledge.md).

Consulta

↓

Query Planner

↓

BM25

+

Vetorial de chunk

+

Vetorial de conceito

+

Knowledge Graph

+

Metadados

+

Recência

+

Autoridade

+

Confiança

↓

Fusion

↓

Re-ranking

↓

Contexto

## Problema conhecido: `unaccent` (achado da Task 14)

A configuração de busca textual `portuguese` do Postgres é sensível a
diacríticos: uma consulta por `existencias` não casa com texto indexado
contendo `existência`. Como falantes de português digitam rotineiramente sem
acento, a perna léxica da recuperação retornaria silenciosamente vazio nesses
casos.

Isso é responsabilidade do K5: instalar a extensão `unaccent` e normalizar o
texto tanto na indexação quanto na consulta, para que a busca lexical não
dependa de o usuário digitar os acentos corretos.