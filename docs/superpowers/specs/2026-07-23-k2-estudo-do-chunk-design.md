# K2 — Estudo do Chunk

> Design aprovado em 2026-07-23. Segundo sub-projeto da reconstrução da camada
> Knowledge. Implementa o Nível 3 de [knowledge.md](../../knowledge.md).
> Depende de [K1](2026-07-23-k1-documento-chunking-hierarquico-design.md).

## 1. Contexto

K1 entregou as duas primeiras camadas: o documento original íntegro e a árvore
estrutural de Livro a Sentença, tudo derivado do texto sem uma única chamada de
LLM. O que existe hoje na base é estrutura pura — nenhuma interpretação.

K2 é onde a IA entra. Ele anota a árvore de K1 com o que o texto *diz*, sem
ainda transformar isso em grafo: a ontologia, as proposições sujeito-relação-
objeto e a escrita no Neo4j são K3.

### 1.1 A pirâmide de compreensão

O estudo não acontece num nível só. Conhecimentos diferentes exigem quantidades
diferentes de contexto, e cada nível consome o resultado do nível abaixo em vez
do texto cru:

```
Nível 1  Extração     Sentença   → claims, conceitos, entidades, citações
Nível 2  Compreensão  Parágrafo  → ideia, resumo, tom, perguntas respondidas
Nível 3  Raciocínio   Seção      → argumentos, evidências, conclusões
Nível 4  Síntese      Capítulo   → mapa conceitual, modelo mental, tese
Nível 5  Conhecimento Livro      → visão global, relação entre capítulos
```

A vantagem do modelo é que o agente de capítulo não relê trezentas páginas: ele
trabalha sobre ideias e argumentos já produzidos. Isso reduz custo, melhora
consistência e torna a troca de modelo um reprocessamento de camada, não do
livro inteiro.

**K2 implementa os dois primeiros degraus.** Os três de cima ficam para K3
(Raciocínio) e K4 (Síntese e Conhecimento).

A razão do corte é a mesma que justifica a pirâmide. Uma sentença isolada
("*Logo, conclui-se que…*") não significa nada; um parágrafo ("*Assim,
Aristóteles demonstra…*") ainda não revela o argumento. Só a seção fecha
premissa e conclusão — e a seção é justamente a unidade que K3 já precisa para
extrair argumento. Cortar aqui alinha a fronteira da pirâmide com a fronteira
que K1 já tinha desenhado entre os sub-projetos.

## 2. Escopo

### Dentro

- Nível 1 da pirâmide, alvo **sentença**: claims, conceitos, entidades, citações.
- Nível 2 da pirâmide, alvo **parágrafo**: ideia principal, resumo, tom,
  conceitos centrais, perguntas respondidas.
- Persistência das anotações no Postgres, bruta e projetada.
- Verificação de citação literal contra o texto original.
- Estudo como segunda fase do fluxo de ingestão por fonte remota.

### Fora

- Seção, capítulo e livro — níveis 3 a 5 da pirâmide (K3/K4).
- Argumento, premissa, conclusão, proposição sujeito-relação-objeto (K3).
- Ontologia e qualquer escrita no Neo4j (K3).
- Canonicalização e dedup de conceito, embedding por conceito (K4).
- Comparação entre livros, contradições, confiança (K6).
- Retriever: continua **dormente** até K5.
- Estudo de arquivo local (`--path`) — ver §4.

## 3. Decisões

Registradas com a justificativa, para não serem relitigadas.

| Decisão | Escolha | Por quê |
|---|---|---|
| Unidade de estudo | Pirâmide multi-escala, K2 cobre sentença e parágrafo | Cada tipo de conhecimento exige uma granularidade. Sentença dá o átomo; parágrafo dá a ideia; argumento precisa de seção e é de K3. |
| Unidade de chamada | Um parágrafo por chamada, saída cobre os dois níveis | Sentença isolada não tem contexto suficiente para ser o *input*, embora seja o *alvo* da anotação. Enumerar os claims antes de nomear a ideia funciona como cadeia de raciocínio. |
| Persistência | Saída crua em JSONB + projeção tipada | Reprojetar o esquema não exige rechamar LLM. K3 e K5 consultam tabelas com índice e FK, não JSONB. |
| Versionamento | Acúmulo por `(chunk_id, modelo, versao_prompt)` | Cumpre a decisão de K1: toda análise entra, conflito resolvido por confiança no Nível 6. Modelo novo insere, não sobrescreve. |
| Disparo | Passo padrão do `ingest`, sem flag | Estudo é parte do fluxo de aquisição de conhecimento, não uma opção a lembrar. |
| Alcance | Só os documentos da invocação atual | Sem varredura de pendentes e sem backfill. O write-once de K1 já garante que documento existente não volta ao conjunto. |
| Caminho de ingestão | Só `--source`/`--query`; `--path` fica sem estudo | Mantém `ingerir_entradas` como K1 puro. A fronteira K1/K2 fica visível na lista de chamadores. |
| Modelo | O mesmo do roteiro, via `build_chat_model` | Nenhuma configuração nova. Custo aceito e registrado em §8. |
| Idioma da anotação | Sempre português; citação literal no original | Base mistura português e inglês. Conceito uniforme facilita K4 e o roteiro. Traduzir citação destruiria a fidelidade que K1 existe para garantir. |

## 4. Onde K2 roda

Estudo é a segunda fase do `ingest`, sem flag:

```
forge ingest --source gutenberg --query "estoicismo"   → K1 + K2
forge ingest --path livro.pdf                          → só K1
```

```
buscar/baixar → extrair → árvore → embed → grava documentos + chunks + vetores
                                                       │  commit
                                                       ▼
                                             estudar parágrafos          [K2]
                                                       ▼
                                          estudos + projeções (Postgres)
```

A separação é estrutural, não documental:

- `ingerir_entradas` continua sendo K1 puro, sem LLM, e não muda.
- `estudar_documentos(entradas, *, model, stores, settings)` é função separada,
  chamada **só** por `ingerir_busca_remota`, depois do commit de K1.
- `ingerir_caminho` não a chama. `--path` e os extratores de PDF/EPUB/TXT ficam
  intactos, produzindo árvore estrutural sem anotação.

K1 commita antes de o estudo começar. Falha de LLM nunca corrompe a árvore.

`ingerir_busca_remota` já monta um `model`, hoje condicionalmente, só quando
alguma fonte declara `idioma_busca`
([ingest.py:153](../../../src/forge/knowledge/ingest.py#L153)). Passa a montar
sempre. O gate de disponibilidade do modelo entra em `_montar`, ao lado do
`sonda_semantica`, para que falta de chave aborte antes de baixar qualquer coisa.

### 4.1 Reconciliação com o critério de conclusão nº1 de K1

K1 declarou que "um livro é ingerido sem uma única chamada de LLM". **K2
substitui esse critério.** A propriedade que permanece verdadeira, e que é a que
importa:

> A fase estrutural não faz nenhuma chamada de LLM. A árvore, os ids e os
> offsets continuam determinísticos e reproduzíveis. O comando `ingest` passa a
> ter uma segunda fase, semântica, que chama LLM.

### 4.2 Consequência aceita

Estudo é uma janela de uso único por documento. Se a rodada falhar no meio,
aquele documento fica parcialmente estudado até um `--reset`, porque reapontar a
mesma busca cai no write-once e não reingere. Mitigação dentro da rodada em §8.

## 5. Contrato da chamada

### 5.1 Input

Um parágrafo, com as sentenças numeradas e um cabeçalho leve de contexto. O
título dos ancestrais é resolvido pelo `caminho` materializado de K1.

```
Obra: Ética a Nicômaco — Aristóteles
Seção: Livro II › 6. A virtude como meio-termo

[S1] A virtude é uma disposição de escolher.
[S2] Ela consiste num meio-termo relativo a nós.
[S3] Como diz Homero, "elogiam-no os que o veem".
```

### 5.2 Output

JSON único cobrindo os dois níveis da pirâmide.

```json
{
  "sentencas": [
    {
      "i": 1,
      "claims": ["A virtude é uma disposição de escolher."],
      "conceitos": ["virtude", "escolha"],
      "entidades": [],
      "citacao": null
    },
    {
      "i": 2,
      "claims": ["A virtude consiste num meio-termo relativo a nós."],
      "conceitos": ["meio-termo"],
      "entidades": [],
      "citacao": null
    },
    {
      "i": 3,
      "claims": [],
      "conceitos": [],
      "entidades": [{"nome": "Homero", "tipo": "outro"}],
      "citacao": {"texto": "elogiam-no os que o veem", "autor": "Homero"}
    }
  ],
  "paragrafo": {
    "ideia": "A virtude é a disposição de escolher o meio-termo.",
    "resumo": "…",
    "tom": "definicao",
    "conceitos": ["virtude", "meio-termo"],
    "perguntas_respondidas": ["O que é a virtude?"]
  }
}
```

`tom` é um conjunto fechado: `definicao`, `explicacao`, `critica`, `exemplo`,
`narrativa`, `citacao`. Valor fora do conjunto é normalizado para `explicacao`.

### 5.3 Regras invioláveis

**O modelo nunca vê nem emite `chunk_id`.** Ele emite o índice `i`; o código
mapeia `i` para o id da sentença pela ordem dos filhos do parágrafo, que K1 já
garante. Id alucinado deixa de ser possível por construção. Índice fora do
intervalo é descartado com log.

**Listar claims antes de nomear a ideia é a cadeia de raciocínio.** A ordem dos
campos no schema é deliberada: a ideia do parágrafo só é emitida depois de o
modelo enumerar o que cada sentença afirma.

**Citação é verificada, não confiada.** `citacao.texto` precisa ser substring
exata da sentença. Se for, o código resolve os offsets absolutos no documento e
grava — a citação vira intervalo verificável, igual a todo o resto de K1. Se não
for exata, a citação é descartada e o resto da anotação é mantido. O modelo não
tem permissão de inventar aspas.

**Anotação em português, citação no original.** `claims`, `conceitos`, `ideia`,
`resumo` e `perguntas_respondidas` saem sempre em português, qualquer que seja o
idioma do livro. `citacao.texto` é sempre a fatia literal do texto original — se
fosse traduzido, deixaria de ser substring e seria descartado pela regra acima,
o que torna a proibição autoexecutável.

### 5.4 Prompt

Markdown em `src/forge/prompts/`, carregado por `load_prompt()`, seguindo a
convenção do projeto: editar o prompt não exige mudança em Python.

`versao_prompt` é o sha256 do template renderizado sem o conteúdo do parágrafo,
truncado em 12 caracteres. Editar o prompt invalida o estudo automaticamente,
sem depender de alguém lembrar de incrementar um número.

## 6. Modelo de dados

Tudo no Postgres. Nada no Neo4j — o grafo começa em K3.

```
estudos
  id             UUID
  chunk_id       -> chunks(id), nível paragrafo
  documento_id   -> documentos(id)
  modelo         identificador do modelo que produziu
  versao_prompt  sha256 do template, 12 chars
  payload        JSONB, saída crua do modelo
  criado_em      TIMESTAMPTZ
  UNIQUE (chunk_id, modelo, versao_prompt)

claims             (id, estudo_id, chunk_id -> sentenca, texto, ordem)
citacoes           (id, estudo_id, chunk_id -> sentenca, texto, autor,
                    offset_inicio, offset_fim)
estudo_conceitos   (estudo_id, chunk_id, nome, nivel)   -- nivel: sentenca | paragrafo
estudo_entidades   (estudo_id, chunk_id, nome, tipo)
ideias             (estudo_id, chunk_id -> paragrafo, ideia, resumo, tom)
```

Toda projeção tem `ON DELETE CASCADE` a partir de `estudos`, e `estudos` a
partir de `chunks` — apagar um documento limpa tudo abaixo.

### 6.1 Acúmulo, não UPDATE

`UNIQUE (chunk_id, modelo, versao_prompt)` significa que um modelo novo insere
uma linha nova e a antiga permanece. Isso cumpre a decisão registrada em K1:
toda análise entra, o conflito é resolvido por confiança no Nível 6.

Uma view `estudo_corrente` devolve a linha mais recente por `chunk_id`. K3 e K5
leem a view, nunca a tabela crua.

### 6.2 Ancoragem só em folha

`claims` e `citacoes` apontam para sentença; `ideias` aponta para parágrafo.
São os dois únicos níveis com id estável sob reingestão (K1 §11). Nenhuma
anotação de K2 referencia nó contêiner.

### 6.3 O que K2 não normaliza

`estudo_conceitos.nome` é a string que o modelo devolveu, sem canonicalização.
"virtude", "a virtude" e "Virtude" convivem. Unificar isso é K4, que dá
embedding próprio ao conceito e faz a dedup. K2 registrar uma canonicalização
ingênua agora só criaria trabalho para K4 desfazer.

## 7. Modelo e configuração

O estudo usa `build_chat_model(settings)`, o mesmo modelo do roteiro. Nenhuma
configuração de provider nova.

Configuração adicionada em `KnowledgeSettings`:

- `estudo_concorrencia: int = 4` — teto de chamadas simultâneas.
- `estudo_max_retries: int = 3` — tentativas por parágrafo antes de desistir.

Injeção segue o padrão já estabelecido na camada: `model` e `stores` entram por
parâmetro em `estudar_documentos`, e as funções de topo montam as dependências
reais a partir de `Settings`. O pipeline de estudo roda inteiro com um model
fake, sem rede e sem Docker.

## 8. Execução, custo e falha

**Concorrência.** Pool de workers sobre os parágrafos, teto em
`estudo_concorrencia`. Parágrafos são independentes: nenhum lê a saída de outro.
Retry com backoff exponencial em erro transitório (429, timeout).

**Falha por parágrafo é isolada.** Esgotadas as tentativas, o parágrafo é logado
com `chunk_id` e o lote segue. A ausência da linha em `estudos` é detectável por
join — não há estado de erro a manter.

**Transação por parágrafo.** A linha em `estudos` e todas as projeções dela são
gravadas na mesma transação. Nunca existe projeção órfã nem `estudos` sem
projeção.

**Custo.** Livro de 300 páginas ≈ 1,5k parágrafos ≈ 1,5M tokens de entrada e
600k de saída. Com o modelo do roteiro (classe Sonnet), da ordem de **US$ 13,50
por livro**. Registrado para ficar explícito, não para reabrir a decisão de §3.

## 9. Testes

O padrão de K1 se mantém: model, embed_fn e stores por injeção, nada de rede,
nada de Docker fora da suite marcada.

**Propriedades centrais** — as três que sustentam K2:

1. **Citação é substring exata.** Model fake que devolve aspas inexistentes no
   texto: a citação é descartada, o resto da anotação é preservado, e há log com
   `chunk_id`.
2. **`i` mapeia para o id certo.** Parágrafo de quatro sentenças, saída
   referenciando `S2`: o claim é ancorado no id da segunda sentença produzida por
   K1.
3. **Acúmulo não sobrescreve.** O mesmo parágrafo estudado com dois
   `versao_prompt` distintos produz duas linhas em `estudos`, e
   `estudo_corrente` devolve a mais recente.

**Demais testes:**

- `i` fora do intervalo do parágrafo é ignorado, sem erro.
- JSON malformado dispara retry; esgotado, o parágrafo é pulado sem derrubar o
  lote.
- `tom` fora do conjunto fechado é normalizado.
- Citação válida resolve offsets absolutos corretos no documento.
- Funções puras de projeção (JSONB → linhas) testadas sem servidor.
- `ingerir_caminho` não produz nenhuma linha em `estudos`.
- Stores reais em suite separada, pulada quando o Docker não está no ar.

## 10. Riscos

| Risco | Mitigação |
|---|---|
| Modelo pula sentenças em parágrafo longo | Sentença sem entrada na saída fica sem anotação, sem erro. Detectável por join. Degrada, não quebra. |
| Conceito com grafia inconsistente | Aceito. Canonicalização e dedup são explicitamente K4. |
| Claim inventado, sem apoio na sentença | Não há verificação automática análoga à da citação. O prompt exige que o claim seja reformulação da sentença, e o `chunk_id` torna a auditoria manual barata. |
| Custo por livro | Registrado em §8. Decisão consciente de reusar o modelo do roteiro. |
| Rodada parcial não é retomável | Aceito em §4.2. Retry e isolamento por parágrafo reduzem a frequência. |

## 11. Contratos para os próximos sub-projetos

| Consumidor | Depende de |
|---|---|
| K3 | ler `claims` e `estudo_conceitos` por seção para montar argumento e ontologia; ancorar proposição em `chunk_id` de sentença |
| K4 | ler `estudo_conceitos` para canonicalizar, embedar e deduplicar conceito |
| K5 | `ideias.resumo` como contexto de entrega small-to-big; `estudo_conceitos` como perna conceitual do retriever |
| K6 | `claims` como unidade de comparação entre livros e de detecção de contradição |

Todos leem pela view `estudo_corrente`, nunca pela tabela `estudos` direta.

## 12. Reconciliação de documentos

| Documento | Ação |
|---|---|
| Spec de K1, critério nº1 | Nota de que K2 o substitui, nos termos de §4.1 |
| `CLAUDE.md` | "Ingestão de K1 não faz nenhuma chamada de LLM" reescrito: fluxo em duas fases, e a assimetria `--source` estuda / `--path` não |
| `docs/knowledge.md` | Não é alterado. Continua sendo a fonte de verdade |

## 13. Critérios de conclusão

1. `forge ingest --source <fonte> --query <tema>` ingere e estuda numa passada,
   sem flag.
2. `forge ingest --path <arquivo>` produz árvore estrutural e nenhuma linha em
   `estudos`.
3. Toda citação persistida é substring exata do texto original, verificável
   pelos offsets.
4. Todo claim e toda citação estão ancorados em `chunk_id` de sentença; toda
   ideia, em `chunk_id` de parágrafo.
5. Reestudar o mesmo documento com prompt alterado acrescenta linhas em vez de
   sobrescrever, e `estudo_corrente` reflete a versão mais recente.
6. A suite roda inteira sem rede, sem chave de API e sem Docker.
