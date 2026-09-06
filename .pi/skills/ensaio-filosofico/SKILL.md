---
name: ensaio-filosofico
description: Escreve um ensaio filosófico em português (800-2000 palavras). Crie um tema no nicho de desenvolvimento pessoal, filosofia e psicologia. Use quando o usuário pedir um ensaio, um texto filosófico ou uma reflexão escrita sobre temas gerais da área de filosofia. A skill cria a tese, pesquisa as citações na web e escreve o ensaio direto no chat.
---

# Ensaio Filosófico

Crie um tema e transforme em um ensaio pronto para publicação, em PT-BR, impresso no chat.

## Entrada e saída

**Entrada:** O usuário não precisa fornecer nada, somente invocar a skill.

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

Regra dura: **se você não chamou `web_search` nesta sessão, o ensaio sai com zero aspas.** Sem exceção. Não há citação legítima possível sem busca, porque sua memória não distingue frase real de frase inventada.

Atenção especial ao título da obra: atribuir a frase certa ao livro errado também é fabricação. Confirme o título junto com a frase, na mesma busca.

**Se uma busca falhar em confirmar, isso é trabalho interno — não aparece no ensaio.** Não escreva no texto final frases como "não encontrei a fonte", "a frase circula mas não localizei", "sem confirmação primária, isso entra como ideia geral". Essa dúvida é sua, resolvida em silêncio nesta etapa: você decide aqui, fora do texto, e o ensaio final só contém a versão parafraseada e sem aspas — nenhum traço da busca malsucedida.

### Etapa 4 — Ensaio

Escreva com tese, esboço e material verificado já definidos. 800 a 2000 palavras, PT-BR.

## Regra de citação

Um modelo de linguagem fabrica citação e atribuição com facilidade. Uma frase inventada na boca de Nietzsche inutiliza o texto inteiro. Por isso:

**O padrão é zero aspas.** Comece pressupondo que este ensaio não terá nenhuma citação literal. Um ensaio forte com zero aspas é o resultado normal e esperado — não é falha, não é preguiça, não é sinal de pouca erudição. Você não precisa de aspas para nomear um filósofo, explicar a ideia dele e discordar dela. Cada aspa é uma exceção que você precisa comprar com uma busca bem-sucedida; se você não pagou esse preço, escreva a ideia com suas próprias palavras. Prefira nunca pagar.

**Nunca escreva uma aspa que você não copiou de um resultado de busca aberto nesta sessão.** Se você está digitando aspas e a frase veio da sua memória em vez de um texto que você acabou de ler na tela, pare e reescreva sem aspas. Não existe "eu tenho certeza que ele disse isso". Essa certeza é exatamente a sensação que acompanha uma citação fabricada.

**Aspas duplas servem para uma coisa só: transcrever uma citação verificada por busca.** Não use aspas para máxima inventada, aforismo anônimo, frase de efeito, nem ênfase. Se uma frase soa como sabedoria de para-choque — "o tédio é um sinal de que algo importante foi abandonado", "isso não merece a sua atenção" — e não tem autor e obra confirmados, ela não vai entre aspas. Aspa sem nome de autor logo em seguida é sempre pseudo-citação: ou você diz de quem é (e comprovou na busca), ou escreve a ideia como sua prosa, sem aspas. Frases como "uma frase ressoa aqui:" seguidas de aspas sem fonte são proibidas.

**Não reaproveite os exemplos deste arquivo de instruções.** As frases de exemplo aqui — a tese sobre o tédio e o "piloto automático", "angústia", "por que eu procrastino?" — são ilustração para você, não material do ensaio. Se a sua tese ou uma frase do texto ficou parecida com um exemplo deste arquivo, reescreva com palavras suas a partir do tema real.

- **Citação literal (entre aspas) só entra com os três confirmados por busca web:** a frase, o autor e a obra.
- **Cada citação exige sua própria chamada de `web_search`.** Nunca reaproveite a busca de uma citação para confirmar outra — mesmo que seja do mesmo autor ou sobre o mesmo tema.
- **Site de coletânea de frases não confirma nada.** Pensador, Frases Fortes, TikTok, X/Twitter, Brainly, Quora, blogs motivacionais e páginas de "citações" reproduzem uns aos outros em círculo. Achar a mesma frase repetida em vários desses sites não é confirmação — é exatamente o padrão de uma pseudo-citação que se espalhou sem nunca ter existido no texto original. Trate esse padrão como sinal de alerta, não como prova.
- **Confirmação exige achar a frase dentro da obra primária.** Depois do `web_search`, use `fetch_content` para localizar a frase no texto original (ou numa fonte acadêmica/editorial que cite capítulo, seção ou página específica). Se você não consegue apontar onde na obra a frase aparece — só sites que a atribuem sem indicar a localização — ela não está confirmada.
- **Faltando qualquer um dos três (frase, autor, obra com localização):** não cite. Parafraseie a ideia e nomeie o autor ou a escola, sem aspas.
- **Frase que você "lembra" mas não encontrou na web é tratada como inexistente.** Sua memória não é fonte.
- **Ideias e conceitos amplamente conhecidos dispensam busca** — a dicotomia do controle dos estoicos, a má-fé sartriana, o eterno retorno. Você pode explicá-los e atribuí-los livremente. Mas frase entre aspas, nunca sem confirmação.
- **Nunca funcione ao contrário.** Não escreva uma frase de efeito que soa filosófica, decida depois que ela "parece coisa que Fulano diria" e a coloque entre aspas com o nome dele. Citação nasce da busca: você encontra a frase pronta na fonte primária, confirma quem a escreveu e onde, e só então a transcreve. Se a frase nasceu da sua própria cabeça — inclusive se ela parece com algum exemplo deste arquivo de instruções — ela é sua prosa, sem aspas e sem nome de autor.

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
- **Meta-narração da própria técnica.** Frases como "isso devolve o problema ao leitor", "eis o contra-argumento honesto", "a resposta final é" nomeiam o que o texto está fazendo em vez de simplesmente fazer. Se uma frase descreve a função retórica do parágrafo em vez de cumprir essa função, corte-a — o leitor nunca deve ver o esqueleto do ensaio.
- **Encher linguiça para bater a contagem de palavras.** 900 palavras densas valem mais que 1800 diluídas.

## Antes de imprimir

Confira, em silêncio:

- [ ] Para cada aspa, houve uma chamada de `web_search` própria (liste mentalmente: aspa → busca feita → resultado), e a frase foi localizada dentro da obra primária ou de fonte que cite capítulo/seção/página — não apenas em site de coletânea de frases.
- [ ] Toda aspa tem frase, autor e obra com localização confirmados por busca web nesta sessão. Nenhuma aspa é aforismo anônimo, máxima inventada ou frase de efeito sem autor logo em seguida.
- [ ] A tese é discutível — não é paráfrase do tema.
- [ ] Existe um contra-argumento honesto no texto.
- [ ] Cada movimento avança a tese.
- [ ] Nenhum antipadrão da lista acima aparece, incluindo meta-narração da própria técnica.
- [ ] A resposta começa no ensaio: sem preâmbulo, sem meta-comentário.

Se algum item falhar, corrija antes de imprimir. Não imprima o resultado da conferência.
