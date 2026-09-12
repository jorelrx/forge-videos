# K1 — Documento Original e Chunking Hierárquico

> Design aprovado em 2026-07-23. Primeiro sub-projeto da reconstrução da camada
> Knowledge. Implementa os Níveis 1 e 2 de [knowledge.md](../../knowledge.md).

## 1. Contexto

[docs/knowledge.md](../../knowledge.md) é a fonte de verdade da camada Knowledge.
Ele descreve seis níveis de representação do conhecimento. O que existe hoje no
código cobre parcialmente três deles, de forma achatada: o documento original não
é persistido, o chunking corta por quantidade de caracteres, e a análise semântica
roda sobre o texto do livro inteiro numa única chamada de LLM.

knowledge.md não cabe num único ciclo de implementação. Foi decomposto em seis
sub-projetos:

| # | Sub-projeto | Níveis | Escopo |
|---|---|---|---|
| **K1** | Documento + Chunking hierárquico | 1-2 | Este documento |
| K2 | Estudo do chunk | 3 | Agentes por chunk: resumo, conceitos, entidades, palavras-chave, citações, classificação temática |
| K3 | Extração de conhecimento | 4 | Ontologia, proposições, argumentos, afirmações no grafo |
| K4 | Conceitos refinados | 5 | Embedding por conceito, dedup/consolidação, grafo hierárquico |
| K5 | Retriever híbrido completo | — | Planner, BM25 multilíngue, vetorial de chunk e conceito, KG, metadados, recência, autoridade, confiança, RRF, cross-encoder |
| K6 | Conhecimento global | 6 | Comparação entre livros, contradições, relações transitivas, confiança, sínteses, lacunas |

Cada um tem seu próprio ciclo spec → plano → implementação. K1 é pré-requisito
duro de todos: K2/K3/K4 anotam o chunk, K5 devolve o chunk.

## 2. Princípio de arquitetura: duas árvores

A camada Knowledge tem duas estruturas que **nunca se misturam**.

**Árvore estrutural** — como o autor escreveu o livro.

```
Livro
└── Capítulo
    └── Subcapítulo
        └── Seção
            └── Parágrafo
                └── Sentença
```

Imutável. Derivada só do texto, sem LLM. Sobrevive a troca de modelo. Mora no
Postgres. É a fonte da verdade.

**Grafo semântico** — como a IA interpretou o livro.

```
Conceito → Ideia → Argumento → Afirmação
```

Evolutivo, descartável, regenerável. Mora no Neo4j. Referencia `chunk_id` da
árvore estrutural, mas nunca é parte dela.

**Consequência obrigatória:** regenerar toda a camada semântica não pode exigir
reingerir a árvore estrutural. Um modelo melhor amanhã roda K2/K3/K4 lendo os
chunks já persistidos — sem re-extrair PDF, sem re-chunkar, sem re-embedar. K1
tem que entregar essa propriedade, senão a separação existe só no desenho.

## 3. Escopo

### Dentro

- Nível 1: documento original persistido íntegro, com hash e metadados completos.
- Nível 2: árvore estrutural de Livro a Sentença, com pai, filhos, caminho,
  capítulo e página.
- Identidade de chunk estável sob reingestão.
- Embedding das folhas-parágrafo (small-to-big).
- Índice léxico por idioma.
- Remoção do que não será usado.
- Reconciliação dos documentos do projeto com knowledge.md.

### Fora

- Qualquer chamada de LLM sobre o conteúdo ingerido (K2 em diante). A aquisição de
  fontes remotas continua funcionando como está, inclusive a tradução do termo de
  busca para fontes só-inglês — ela traduz a query, nunca o conteúdo.
- Níveis "Ideia" e "Argumento" da hierarquia — são semânticos, vão para K2/K3.
- Qualquer escrita no Neo4j (começa em K3).
- Retriever: fica **dormente** até K5.

## 4. Decisões

Registradas com a justificativa, para não serem relitigadas.

| Decisão | Escolha | Por quê |
|---|---|---|
| Onde mora o original | Texto extraído em coluna no Postgres, hash sobre ele | Uma fonte, transacional. Trade-off aceito: se o extrator melhorar, não há binário original para reprocessar. |
| Fronteira de Ideia/Argumento | Fora de K1 — só estrutural | Fronteira limpa entre sub-projetos; segmentação semântica é trabalho de K2/K3, que já extraem premissa e conclusão. |
| Granularidade de recuperação | Small-to-big | Embeda a folha-parágrafo (vetor preciso), devolve subindo pelo pai (contexto de leitura). Um vetor por parágrafo. |
| Página | Real quando existe + localizador hierárquico sempre | PDF tem página de verdade; EPUB/TXT não têm nenhuma. Página sintética seria número inventado — citação falsamente precisa. |
| Dono da hierarquia | A própria árvore estrutural, no Postgres | Duas árvores separadas (§2). O grafo semântico referencia, não contém. |
| Regeneração semântica | Acúmulo com dedup | Toda análise entra; conflito resolvido por confiança (Nível 6). Impõe identidade de chunk estável. |
| Índice léxico multilíngue | `tsvector` por idioma via `CASE` | SEP e Gutenberg trazem inglês; stemmer português degrada a perna BM25. `CASE` com configs literais é `IMMUTABLE`, logo válido em generated column. |
| Migração | Reingestão do zero (`--reset`) | Base ainda é pequena, pipeline é idempotente. Sem código de migração para manter; garante que todo documento tem todos os sinais. |
| Brief do LLM na base | Parar de ingerir | Reingerir prosa do modelo como se fosse pesquisa contamina a base e briga com "priorizar fontes primárias". |
| Paliativos | Nenhum | O que não vai ser usado sai do pipeline em vez de ser carregado truncado. |

## 5. Modelo de dados

### 5.1 `documentos` — Nível 1

```
id                UUID determinístico, derivado do hash
hash_sha256       hash do texto extraído
texto             extração crua, íntegra, nunca alterada
titulo, autor, obra, edicao, isbn
idioma, licenca, fonte, url, tipo, autoridade
data_publicacao, data_ingestao
```

`documento.id` passa a derivar do `hash_sha256`. Hoje deriva de nome do arquivo +
tamanho ([book.py:33](../../../src/forge/knowledge/sources/book.py#L33)) — renomear
o arquivo cria um documento duplicado.

`resumo` sai da tabela em K1 e volta em K2 como artefato semântico.

### 5.2 `chunks` — Nível 2

```
id              identidade por conteúdo (§5.3)
documento_id
pai_id          auto-referência; NULL na raiz
nivel           livro | capitulo | subcapitulo | secao | paragrafo | sentenca
caminho         materializado, ex '0003.0002.0004'
ordem
titulo          nome da seção, quando o nível tem um
texto           fatia exata por offset do original
pagina          real no PDF, NULL em EPUB/TXT
offset_inicio, offset_fim
```

- `filhos` = quem aponta `pai_id`; não é coluna.
- `capitulo` = ancestral de nível capítulo, resolvido pelo `caminho`; não é coluna.
- `contexto` (do desenho em knowledge.md) é derivado na leitura via small-to-big;
  não é coluna.
- `resumo`, `tema`, `conceitos` (do desenho em knowledge.md) são semânticos:
  preenchidos por K2, não por K1.

### 5.3 Identidade de chunk

```
chunk.id = id_deterministico(documento_id, sha256(texto), ocorrencia)
```

Identidade vem do **conteúdo**, não da posição. `caminho`, `ordem` e `pai_id` são
atributos mutáveis. `ocorrencia` desempata texto repetido no mesmo documento
(epígrafe repetida, "Ibid.").

Hoje é `id_deterministico(documento_id, ordem)` — ordinal global. Inserir um
parágrafo no capítulo 1 muda o id de todo chunk seguinte, o que é incompatível com
acúmulo: toda aresta semântica acumulada em K2-K4 viraria órfã na primeira
reprocessada.

O hash é sobre a fatia crua, não sobre texto normalizado. Se fosse sobre o texto
normalizado, trocar a versão do normalizador mudaria todos os ids.

## 6. Pipeline

```
arquivo
  ↓ extrair      PDF/EPUB/TXT/MD → texto + offsets de página + marcas de cabeçalho
  ↓ Nível 1      grava documentos: texto íntegro + hash + metadados
  ↓ árvore       capítulo/subcapítulo/seção → parágrafo → sentença
  ↓ persistir    chunks no Postgres, vetores das folhas-parágrafo no Qdrant
```

Sem LLM em nenhum passo. Determinístico e reproduzível.

### 6.1 Extração preservando estrutura

`carregar_livro` hoje joga tudo numa string e descarta página e marcação
([book.py:43-79](../../../src/forge/knowledge/sources/book.py#L43-L79)). Passa a
devolver texto + marcas:

- **PDF**: as páginas são concatenadas por nós, registrando o offset acumulado de
  cada uma — controle nosso, não do extrator. Cabeçalho por heurística de
  numeração e caixa.
- **EPUB**: o spine dá o capítulo real; `<h1>`-`<h6>` dão subcapítulo e seção. É o
  melhor sinal estrutural dos três formatos e hoje é descartado pelo `get_text()`.
- **TXT/MD**: `#` markdown e regex de `Capítulo N`, como
  [structure.py:12-18](../../../src/forge/knowledge/pipeline/structure.py#L12-L18)
  já faz — mas produzindo hierarquia aninhada em vez de lista plana.

### 6.2 Texto nunca é alterado, nem no chunk

`chunks.texto` é fatia exata por offset do original. Normalização (caixa, unicode,
hífen de quebra de linha) existe apenas como entrada transitória do `tsvector` e do
embedding; nunca é persistida como texto.

### 6.3 Níveis persistidos e embedados

Persistidos até **sentença**: é onde K3 vai ancorar proposição e citação, e âncora
precisa de id estável, logo precisa de linha. Um livro de 300 páginas dá ≈1,5k
parágrafos e ≈5k sentenças — irrelevante para o Postgres.

Embedados: só a folha-**parágrafo**. Sentença, seção e capítulo não viram vetor.

### 6.4 Persistência por store

| Store | K1 escreve |
|---|---|
| Postgres | `documentos` (Nível 1 completo) + `chunks` (árvore inteira) + `tsvector` por idioma |
| Qdrant | um ponto por parágrafo; payload com `chunk_id`, `pai_id`, `caminho`, `capitulo`, `pagina` e proveniência |
| Neo4j | nada — grafo é da camada semântica, começa em K3 |

## 7. Remoções

Sai do pipeline de ingestão (volta em K2 com escopo de chunk):

- `resumir`, `extrair_entidades`, `extrair_relacionamentos`, `extrair_conceitos`
- `chunk_documento` por caracteres; `chunk_size` e `chunk_overlap` da config
- `Documento.secoes` e o modelo `Secao` — substituídos pela árvore
- `GraphStore.upsert_documento` fica sem chamador até K3

Retriever fica **dormente** até K5:

- comando `buscar` sai do parser da CLI
- `consultar_e_aprender` sai do `node_research`; `knowledge_enabled` deixa de ter
  efeito no fluxo de roteiro durante K1-K4
- `hybrid.py` permanece no repositório, marcado como dormente: a fusão RRF está
  correta e é reaproveitada em K5

Efeito colateral aceito: entre K1 e K2 a base não tem resumo, entidades nem grafo.

## 8. CLI

`forge ingest --reset` derruba e recria os três stores, para reingestão do zero.

> **Aviso:** `--reset` apaga de forma irreversível todos os dados dos três stores.
> Exige confirmação: por padrão pede confirmação interativa digitando o nome de
> cada store; `--sim` pula o prompt e existe apenas para automação.

## 9. Testes

O pipeline de K1 é puro e sem LLM, então quase tudo é testável sem Docker e sem
rede. Isso também cobre a lacuna atual: chunk, embed, ingest, retriever e stores
não têm nenhum teste commitado hoje.

**Propriedades centrais** — as duas que sustentam o design:

1. **Fidelidade**: recompor as folhas-parágrafo pelos offsets reproduz o texto
   original byte a byte. Se falhar, a citação mente.
2. **Estabilidade sob reingestão**: inserir um parágrafo no meio do livro e
   reingerir preserva o id de todos os outros chunks. É o que prova que a camada
   semântica acumulada sobrevive.

**Demais testes:**

- Extração: PDF de 3 páginas devolve offsets corretos; EPUB usa o spine como
  capítulo; MD aninha `##` sob `#`.
- Árvore: caminho materializado ordena corretamente; `LIKE '0003.%'` recorta a
  subárvore.
- Sentença: split determinístico com abreviação, reticências e citação.
- Funções puras: `linha_documento`, `linha_chunk`, `_payload`.
- Stores reais: suite separada, pulada quando o Docker não está no ar.

Segue o padrão de injeção já estabelecido na camada: `model`, `embed_fn` e
`stores` entram por parâmetro, e as funções de topo montam as dependências reais a
partir de `Settings`.

## 10. Riscos

| Risco | Mitigação |
|---|---|
| Heurística de cabeçalho falha em PDF diagramado | Sem capítulo detectado, o documento vira raiz direto sobre parágrafos. Degrada, não quebra. |
| `pypdf` não garante offset estável | As páginas são concatenadas por nós, com offset acumulado registrado no processo. |
| EPUB com HTML sujo gera parágrafo lixo | Folha com menos de 40 caracteres é mesclada no vizinho seguinte. |
| Extrator mudar invalida ids de chunk | Aceito e documentado: mudança de extrator é migração declarada, não silenciosa. |

## 11. Contratos para os próximos sub-projetos

| Consumidor | Depende de |
|---|---|
| K2 | ler chunks por documento e por nível; `chunk_id` estável para anotar |
| K3 | ancorar proposição e citação em `chunk_id` de sentença |
| K4 | subir a árvore pelo `caminho` para ligar conceito à seção |

> **Só `paragrafo` e `sentenca` têm id anotável.** O id de um nó contêiner
> (livro, capítulo, subcapítulo, seção) é o hash do intervalo inteiro da subárvore,
> então muda a cada alteração de conteúdo em qualquer ponto abaixo dele. K2-K4
> devem ancorar anotação em folha; para endereçar uma seção de forma estável, use
> `(documento_id, caminho)`, que é UNIQUE no Postgres, e não o `chunk_id` dela.
| K5 | small-to-big: dado o parágrafo, subir ao pai e devolver com contexto |

Nenhum deles deve precisar reescrever K1. Se algum precisar, a fronteira está
errada.

## 12. Reconciliação de documentos

`docs/knowledge.md` é a fonte única e **não é alterado**.

| Documento | Ação |
|---|---|
| `docs/Base_de_conhecimento.md` | Fluxo linear achatado, superado pelos seis níveis. Vira ponteiro de uma linha para knowledge.md. |
| `docs/RAG_retriever_hibrido.md` | Continua válido; ganha `confiança` e `embedding de conceito` nos sinais, e nota de que é escopo de K5. |
| `docs/CreatorBrain_Plataforma_Arquitetura_Visao.md` | Seção "Pipeline RAG" aponta para knowledge.md; roadmap V2 reescrito como K1→K6. |
| `CLAUDE.md` | Seção "Knowledge layer / RAG" reescrita: duas árvores, small-to-big, identidade por conteúdo, retriever dormente. |
| `README.md` | Estrutura de módulos desatualizada. |

## 13. Critérios de conclusão

1. Um livro local de 500 mil caracteres é ingerido sem uma única chamada de LLM
   (a tradução de termo de busca em fonte remota é a única chamada que resta na
   camada, e não toca o conteúdo).
2. As folhas recompõem o texto original byte a byte.
3. Um parágrafo inserido no meio do livro não altera o id das demais **folhas**
   (`paragrafo` e `sentenca`). Nós contêineres mudam de id por construção — ver
   a nota em §11.
4. K1-K4 não dependem de retriever nenhum: o fluxo de roteiro roda com a camada
   Knowledge inteiramente desacoplada.
5. Os documentos da §12 estão reconciliados e apontam para knowledge.md.
