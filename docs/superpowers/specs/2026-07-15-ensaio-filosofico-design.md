# Skill `ensaio-filosofico` — Design

Data: 2026-07-15
Status: aprovado, pronto para plano de implementação

## Objetivo

Primeira feature da pipeline `forge-videos`: um gerador de ensaios filosóficos que roda como skill do harness Pi, com modelo local (LM Studio, `qwen/qwen3.5-9b`).

O agente recebe um tema e devolve um ensaio pronto em PT-BR, sem intervenção no meio do caminho.

## Escopo

**Dentro:**

- Um arquivo `SKILL.md` em `.pi/skills/ensaio-filosofico/`, versionado no repo.
- Ensaio em PT-BR, 800–2000 palavras, impresso no chat.
- Nicho: Desenvolvimento Pessoal, Filosofia e Psicologia.

**Fora:**

- Roteiro de vídeo, marcação de cenas, timing.
- Escrita de arquivos de saída (`output/*.md`) — o texto só vai pro chat.
- Código Python, dependências novas, estágios seguintes da pipeline.

## Contexto do harness

Pi está instalado em `~/.pi/agent/` com:

- `defaultProvider: lmstudio/desktop`, `defaultModel: qwen/qwen3.5-9b`, `defaultThinkingLevel: high`
- Pacote `pi-web-access` (tools `web_search` e `fetch_content`)
- Pacote `pi-lmstudio`

Pi descobre skills em `.pi/skills/` a partir do `cwd` subindo pelos diretórios pai, além de `~/.pi/agent/skills/`. Uma skill é um diretório com `SKILL.md` (frontmatter + instruções). O agente carrega a skill sozinho quando a `description` casa com a tarefa; `/skill:ensaio-filosofico` força o carregamento.

## Artefato

Arquivo único: `.pi/skills/ensaio-filosofico/SKILL.md`

Frontmatter:

- `name: ensaio-filosofico`
- `description:` redigida para disparar em pedidos de ensaio ou texto filosófico, citando o nicho (desenvolvimento pessoal, filosofia, psicologia).

Entrada: um tema em qualquer nível de vagueza — de uma palavra ("angústia") a uma pergunta ("por que procrastino").

Saída: o ensaio, direto no chat. Nada mais.

## Fluxo interno

A skill instrui o agente a executar quatro etapas em sequência, sem checkpoint com o usuário:

1. **Tese** — converter o tema em afirmação discutível, com a qual alguém razoável poderia discordar. "Sobre o tédio" não é tese; "o tédio é a única coisa que te informa que tua vida virou piloto automático" é.
2. **Esboço** — forma livre, escolhida conforme o tema. A skill não fixa esqueleto. Fixa o critério: cada movimento precisa avançar a tese, não repeti-la.
3. **Pesquisa** — `web_search` para confirmar cada citação e atribuição; `fetch_content` quando o resultado da busca não bastar. Roda antes de escrever, não durante.
4. **Ensaio** — escrever com tese, esboço e material verificado já definidos.

As etapas 1 a 3 são trabalho interno. O chat recebe apenas o ensaio final.

## Regra de citação

Motivação: um modelo 9b fabrica citação e atribuição com facilidade. Frase inventada na boca de Nietzsche inutiliza o texto para a pipeline.

Regra:

- Citação literal só entra se a busca web confirmou os três: a frase, o autor e a obra.
- Faltando qualquer um dos três: não cita. Parafraseia a ideia e nomeia autor ou escola, sem aspas.
- Frase que o modelo "lembra" mas não encontrou na web é tratada como inexistente.
- Ideias e conceitos amplamente conhecidos (dicotomia do controle, má-fé sartriana) dispensam busca. Frase entre aspas, nunca.

## Voz

Híbrido de duas vozes:

- **Divulgação autoral** — primeira pessoa, linguagem acessível, sem jargão não explicado.
- **Reflexiva/contemplativa** — provoca o leitor, prosa que respira.

Regras concretas:

- Concreto antes de abstrato: o exemplo cotidiano vem primeiro, o conceito depois.
- Um contra-argumento honesto em algum ponto do texto. A skill exige que exista; não fixa onde.
- O argumento é real: o texto sustenta a tese, não passeia em volta dela.

## Antipadrões

A skill lista explicitamente, porque um modelo 9b cai neles por padrão:

- Abertura de dicionário ("Desde os primórdios da humanidade...").
- Citação decorativa, que não trabalha no argumento.
- Autoajuda com verniz filosófico.
- Fecho que dissolve a tensão numa frase de efeito.

## Verificação

Rodar Pi dentro do repo e gerar ensaios sobre dois temas — um com filósofo óbvio associado, um sem. Conferir:

- Toda aspa tem fonte rastreável (frase + autor + obra).
- A tese é discutível, não é paráfrase do tema.
- Tamanho entre 800 e 2000 palavras.
- Nenhum antipadrão da lista acima aparece.

## Risco conhecido

Estrutura livre num modelo 9b tende a divagar. Escolha deliberada do usuário. Se o primeiro ensaio sair frouxo, o conserto é apertar a etapa de esboço — não bloqueia a implementação agora.
