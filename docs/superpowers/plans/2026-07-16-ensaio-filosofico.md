# Skill `ensaio-filosofico` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar uma skill do harness Pi que transforma um tema em ensaio filosófico de 800-2000 palavras em PT-BR, impresso no chat, com citações verificadas na web.

**Architecture:** Um único arquivo `SKILL.md` em `.pi/skills/ensaio-filosofico/`, versionado no repo. Sem código, sem dependências novas. A skill é instrução em prosa: o agente Pi lê o `SKILL.md` e executa quatro etapas internas (tese → esboço → pesquisa → ensaio) numa tacada, sem checkpoint com o usuário.

**Tech Stack:** Pi coding agent (`@earendil-works/pi-coding-agent`), LM Studio local em `http://127.0.0.1:1234` com `qwen/qwen3.5-9b`, pacote `pi-web-access` (tools `web_search` e `fetch_content`).

**Spec:** `docs/superpowers/specs/2026-07-15-ensaio-filosofico-design.md`

## Global Constraints

- Idioma do ensaio e do conteúdo da skill: PT-BR.
- Tamanho do ensaio: 800 a 2000 palavras.
- Saída: apenas o chat. A skill nunca grava arquivo de ensaio.
- Entregável: um único arquivo, `.pi/skills/ensaio-filosofico/SKILL.md`. Sem código, sem dependência nova, sem `output/`.
- Frontmatter obrigatório: `name` (1-64 chars, minúsculas, números e hífens; sem hífen inicial/final; sem hífen duplo) e `description` (máx. 1024 chars).
- Nicho: Desenvolvimento Pessoal, Filosofia e Psicologia.
- Citação literal só com frase, autor e obra confirmados por busca web. Faltando qualquer um dos três: parafrasear sem aspas.
- Pré-requisitos de execução: LM Studio rodando em `http://127.0.0.1:1234` com `qwen/qwen3.5-9b` carregado.
- Trust: skills de `.pi/skills/` são recurso protegido por project trust. Modo `-p` não mostra prompt de trust — sem decisão salva, a skill é ignorada em silêncio. Toda invocação de `pi` neste plano usa `--approve`/`-a`, que concede trust por execução, sem gravar decisão em `~/.pi/agent/trust.json`. Nunca rodar `pi` sem `-p` (sessão interativa trava a automação).

---

### Task 1: Escrever a skill e confirmar que o Pi a descobre

**Files:**
- Create: `.pi/skills/ensaio-filosofico/SKILL.md`

**Interfaces:**
- Consumes: tools `web_search` e `fetch_content`, fornecidas pelo pacote `pi-web-access` (já instalado em `~/.pi/agent/settings.json`).
- Produces: skill de nome `ensaio-filosofico`, invocável por `/skill:ensaio-filosofico <tema>` ou por descrição. Tasks 2 e 3 dependem desse nome exato.

- [ ] **Step 1: Criar o arquivo da skill**

Criar `.pi/skills/ensaio-filosofico/SKILL.md` com exatamente este conteúdo:

````markdown
---
name: ensaio-filosofico
description: Escreve um ensaio filosófico em português (800-2000 palavras) a partir de um tema, no nicho de desenvolvimento pessoal, filosofia e psicologia. Use quando o usuário pedir um ensaio, um texto filosófico ou uma reflexão escrita sobre temas como tédio, angústia, procrastinação, hábito, sentido, liberdade, culpa ou identidade. A skill cria a tese, pesquisa as citações na web e escreve o ensaio direto no chat.
---

# Ensaio Filosófico

Transforma um tema em ensaio pronto para publicação, em PT-BR, impresso no chat.

## Entrada e saída

**Entrada:** um tema, em qualquer nível de vagueza — de uma palavra ("angústia") a uma pergunta ("por que eu procrastino?").

**Saída:** o ensaio, e só ele. Sem preâmbulo, sem "aqui está o ensaio", sem título de seção anunciando as etapas, sem meta-comentário no fim, sem oferta de revisão. O primeiro caractere da resposta é a primeira palavra do ensaio.

Nunca grave arquivo. O ensaio vai para o chat.

## Fluxo

Execute as quatro etapas em ordem, sozinho. Não pergunte nada ao usuário — nem tema, nem ângulo, nem aprovação de esboço. As etapas 1 a 3 são trabalho interno: pense nelas, não as imprima.

### Etapa 1 — Tese

Converta o tema numa afirmação discutível: alguém razoável precisa poder discordar dela.

- "Sobre o tédio" não é tese. É assunto.
- "O tédio é a única coisa que te informa que tua vida virou piloto automático" é tese.

Teste antes de seguir: existe uma pessoa inteligente que defenderia o contrário? Se não existe, a tese é banal — reescreva.

### Etapa 2 — Esboço

Escolha a forma que o tema pede. Não existe esqueleto fixo: um tema pode pedir narrativa, outro pede desmontagem de um argumento, outro pede confronto entre duas escolas.

Critério único, inegociável: cada movimento do texto avança a tese. Se um movimento apenas reformula o anterior em outras palavras, corte.

Decida também, aqui, onde entra o contra-argumento honesto (ver seção Voz).

### Etapa 3 — Pesquisa

Antes de escrever a primeira frase do ensaio, resolva todas as citações.

Use `web_search` para confirmar cada citação que você pretende usar. Use `fetch_content` quando o resultado da busca não for suficiente para confirmar frase, autor e obra.

Se a busca não confirmar, a citação não existe para efeito deste ensaio. Não escreva com aspas.

### Etapa 4 — Ensaio

Escreva com tese, esboço e material verificado já definidos. 800 a 2000 palavras, PT-BR.

## Regra de citação

Um modelo de linguagem fabrica citação e atribuição com facilidade. Uma frase inventada na boca de Nietzsche inutiliza o texto inteiro. Por isso:

- **Citação literal (entre aspas) só entra com os três confirmados por busca web:** a frase, o autor e a obra.
- **Faltando qualquer um dos três:** não cite. Parafraseie a ideia e nomeie o autor ou a escola, sem aspas.
- **Frase que você "lembra" mas não encontrou na web é tratada como inexistente.** Sua memória não é fonte.
- **Ideias e conceitos amplamente conhecidos dispensam busca** — a dicotomia do controle dos estoicos, a má-fé sartriana, o eterno retorno. Você pode explicá-los e atribuí-los livremente. Mas frase entre aspas, nunca sem confirmação.

Na dúvida entre citar e parafrasear: parafraseie.

## Voz

Duas vozes ao mesmo tempo:

**Divulgação autoral** — primeira pessoa. Linguagem acessível. Nenhum jargão sem explicação; se usar "fenomenologia", explique em linguagem de gente na mesma frase. Você escreve para quem nunca leu o filósofo e merece entendê-lo mesmo assim.

**Reflexiva e contemplativa** — você provoca o leitor, não o instrui. A prosa respira: frases de comprimentos diferentes, silêncios, perguntas que ficam.

Regras concretas:

- **Concreto antes de abstrato.** O exemplo cotidiano vem primeiro, o conceito depois. Nunca abra um movimento com definição.
- **Um contra-argumento honesto**, em algum ponto do texto. Honesto significa: a objeção mais forte contra a sua tese, apresentada na melhor versão dela — não um espantalho fácil de derrubar.
- **O argumento é real.** O texto sustenta a tese, não passeia em volta dela.
- **Você tem uma posição.** Ensaio não é resumo neutro do que os filósofos pensaram sobre o assunto.

## Antipadrões

Não faça nada disto:

- **Abertura de dicionário.** "Desde os primórdios da humanidade...", "O tédio, do latim *taedium*, significa...". Comece no concreto: uma cena, um gesto, um incômodo reconhecível.
- **Citação decorativa.** Citação que poderia ser deletada sem o argumento perder nada. Se a frase citada não faz trabalho, corte a frase.
- **Autoajuda com verniz filosófico.** Lista de passos, "a chave é", promessa de solução, otimismo obrigatório no fim.
- **Fecho que dissolve a tensão.** Frase de efeito que finge resolver o que o ensaio abriu. O fecho devolve o problema ao leitor, com mais nitidez do que ele tinha na abertura.
- **Encher linguiça para bater a contagem de palavras.** 900 palavras densas valem mais que 1800 diluídas.

## Antes de imprimir

Confira, em silêncio:

- [ ] Toda aspa tem frase, autor e obra confirmados por busca web nesta sessão.
- [ ] A tese é discutível — não é paráfrase do tema.
- [ ] Existe um contra-argumento honesto no texto.
- [ ] Cada movimento avança a tese.
- [ ] Nenhum antipadrão da lista acima aparece.
- [ ] A resposta começa no ensaio: sem preâmbulo, sem meta-comentário.

Se algum item falhar, corrija antes de imprimir. Não imprima o resultado da conferência.
````

- [ ] **Step 2: Verificar que o Pi descobre a skill e valida o frontmatter**

Rodar, a partir de `c:\dev\forge-videos`:

```bash
pi -a --no-session -p "Liste as skills disponíveis pelo nome, uma por linha. Não faça mais nada."
```

Esperado: `ensaio-filosofico` aparece na lista. Nenhum warning de validação de frontmatter no output.

O `-a` é obrigatório: sem ele, `.pi/skills/` é ignorado em silêncio (ver Global Constraints).

Se aparecer warning de frontmatter, corrigir `name`/`description` conforme as regras em Global Constraints e repetir.

- [ ] **Step 3: Commit**

```bash
git add .pi/skills/ensaio-filosofico/SKILL.md
git commit -m "feat: add ensaio-filosofico Pi skill"
```

---

### Task 2: Verificar com tema de filósofo óbvio

Um tema que puxa um filósofo canônico é onde o modelo mais tende a fabricar citação. É o teste da regra de citação.

**Files:**
- Modify (somente se a verificação reprovar): `.pi/skills/ensaio-filosofico/SKILL.md`

**Interfaces:**
- Consumes: skill `ensaio-filosofico` da Task 1.
- Produces: nada que tasks posteriores consumam. Entrega evidência de que a regra de citação segura.

- [ ] **Step 1: Confirmar que o LM Studio responde**

```bash
curl -s http://127.0.0.1:1234/v1/models
```

Esperado: JSON listando modelos, com `qwen/qwen3.5-9b` entre eles. Se conexão recusada: abrir o LM Studio, carregar o modelo, ligar o servidor local, repetir.

- [ ] **Step 2: Gerar o ensaio**

Rodar de `c:\dev\forge-videos`:

```bash
pi -a --no-session -p "/skill:ensaio-filosofico o tédio" > ensaio-tedio.txt
```

Esperado: arquivo com um ensaio em PT-BR. O `> ensaio-tedio.txt` é só para inspeção nesta verificação — o arquivo não entra no git.

- [ ] **Step 3: Contar palavras**

```bash
wc -w ensaio-tedio.txt
```

Esperado: entre 800 e 2000.

- [ ] **Step 4: Auditar as citações**

Ler `ensaio-tedio.txt`. Para cada trecho entre aspas, buscar a frase na web e confirmar autor e obra.

Aprovado: toda aspa confirmada. Uma aspa fabricada reprova a task.

- [ ] **Step 5: Auditar tese, contra-argumento e antipadrões**

Ler o ensaio e responder:

- A primeira frase é concreta, não definição de dicionário?
- A tese é discutível — dá para alguém razoável defender o contrário?
- Existe um contra-argumento honesto, na melhor versão da objeção?
- O fecho devolve o problema ao leitor em vez de resolvê-lo com frase de efeito?
- A resposta começa no ensaio, sem preâmbulo tipo "Aqui está o ensaio:"?

Qualquer "não" reprova a task.

- [ ] **Step 6: Corrigir a skill se algo reprovou**

Para cada reprovação, apertar a instrução correspondente no `SKILL.md` — deixar a regra mais específica e concreta, não apenas mais enfática. Exemplos:

- Aspa fabricada: reforçar na regra de citação que cada aspa exige uma chamada de `web_search` própria, e que a checagem final lista as buscas feitas.
- Ensaio divagou: apertar a Etapa 2 — exigir que o esboço nomeie cada movimento e a frase da tese que ele avança.
- Preâmbulo apareceu: reforçar em Entrada e saída que o primeiro caractere é a primeira palavra do ensaio.

Depois de corrigir, repetir os Steps 2 a 5 até aprovar.

- [ ] **Step 7: Limpar o arquivo temporário**

```bash
rm ensaio-tedio.txt
```

- [ ] **Step 8: Commit (somente se o SKILL.md mudou)**

```bash
git add .pi/skills/ensaio-filosofico/SKILL.md
git commit -m "fix: tighten ensaio-filosofico rules after canonical-theme run"
```

Se o `SKILL.md` não mudou, não há commit nesta task.

---

### Task 3: Verificar com tema sem filósofo óbvio

Tema sem canônico associado testa o outro lado: o modelo pode forçar um filósofo que não tem nada a ver, ou escorregar para autoajuda por falta de âncora filosófica.

**Files:**
- Modify (somente se a verificação reprovar): `.pi/skills/ensaio-filosofico/SKILL.md`

**Interfaces:**
- Consumes: skill `ensaio-filosofico`, já aprovada na Task 2.
- Produces: nada que tasks posteriores consumam.

- [ ] **Step 1: Gerar o ensaio**

Rodar de `c:\dev\forge-videos`:

```bash
pi -a --no-session -p "/skill:ensaio-filosofico por que eu adio o que eu mesmo escolhi fazer" > ensaio-adiamento.txt
```

Esperado: arquivo com um ensaio em PT-BR.

- [ ] **Step 2: Contar palavras**

```bash
wc -w ensaio-adiamento.txt
```

Esperado: entre 800 e 2000.

- [ ] **Step 3: Auditar as citações**

Ler `ensaio-adiamento.txt`. Para cada trecho entre aspas, buscar a frase na web e confirmar autor e obra. Uma aspa fabricada reprova a task.

- [ ] **Step 4: Auditar o encaixe filosófico e o nicho**

Ler o ensaio e responder:

- O filósofo ou a escola citada tem relação real com o tema, ou foi enfiado à força para o texto parecer filosófico?
- O texto escapou para autoajuda — lista de passos, "a chave é", promessa de solução?
- A tese é discutível?
- Existe um contra-argumento honesto?

Qualquer resposta ruim reprova a task.

- [ ] **Step 5: Corrigir a skill se algo reprovou**

Apertar a instrução correspondente no `SKILL.md`, sempre de forma específica. Exemplos:

- Filósofo forçado: acrescentar aos antipadrões que é melhor um ensaio sem nenhum filósofo nomeado do que um filósofo puxado pelos cabelos, e que a Etapa 3 só pesquisa o que o esboço realmente pede.
- Escorregou para autoajuda: tornar o antipadrão concreto listando as frases proibidas ("a chave é", "o segredo está em", "três passos para").

Depois de corrigir, repetir os Steps 1 a 4 até aprovar. Se a correção mexer em regra usada pela Task 2, rodar de novo o tema "o tédio" e conferir que continua aprovado.

- [ ] **Step 6: Limpar o arquivo temporário**

```bash
rm ensaio-adiamento.txt
```

- [ ] **Step 7: Commit (somente se o SKILL.md mudou)**

```bash
git add .pi/skills/ensaio-filosofico/SKILL.md
git commit -m "fix: tighten ensaio-filosofico rules after open-theme run"
```

Se o `SKILL.md` não mudou, não há commit nesta task.
