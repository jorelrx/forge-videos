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
