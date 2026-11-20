---
name: conquistas-cosmicas
description: Gera roteiros filosóficos para vídeos longos (10-20 min) do canal de YouTube "Conquistas Cósmicas", com tom calmo e reflexivo. Cobre quatro eixos — Estoicismo, Filosofia do Autoconhecimento, Niilismo/Absurdo, e Ética Digital e IA — sempre com embasamento real (filósofos, obras e ideias verdadeiras) e citações verificadas, nunca inventadas. Use esta skill sempre que o usuário pedir um roteiro, texto, script, narração ou vídeo sobre filosofia, estoicismo, sentido da vida, autoconhecimento, propósito, solidão, niilismo, o absurdo, ou ética/liberdade/privacidade diante da tecnologia e da IA — mesmo que ele não diga explicitamente "roteiro" ou "Conquistas Cósmicas". Também vale quando pedir título, gancho de abertura, ou sugestões de cenas/imagens para um vídeo filosófico.
---

# Conquistas Cósmicas — Roteiros Filosóficos

Esta skill gera roteiros completos para o canal **Conquistas Cósmicas**: vídeos longos (10-20 minutos) de filosofia reflexiva, com narração em português do Brasil.

A prioridade absoluta é **embasamento real**. O canal se sustenta na credibilidade: filósofos reais, obras reais, ideias corretamente representadas e citações que de fato foram ditas. Uma única citação inventada pode custar a confiança do público. Trate isso como inegociável (ver **Protocolo de Citações** abaixo).

## Pesquisa no forge-videos

**A única fonte de pesquisa é a API do acervo**, configurada por `FORGE_ACERVO_URL` (padrão `http://127.0.0.1:8000`). Use o cliente `Acervo` de `src/forge/services/acervo.py`, como o agente em `src/forge/agents/research.py`: formule queries dirigidas, chame `buscar(q, top=8)`, deduplique por `Passagem.path` e examine a relevância do texto retornado antes de escrever. Quando executar o pipeline, preserve seu juiz de relevância e suas regras de lacunas; numa execução direta da skill, registre a avaliação das passagens sem alegar que o juiz do pipeline foi executado.

Os arquivos temáticos de `references/` orientam a formulação das queries; não substituem evidências do acervo. Toda atribuição filosófica, inclusive paráfrases, precisa estar sustentada por uma passagem retornada. Copie `path`, `book_id`, título, autores e texto da resposta, sem reconstruir referências de memória. Preserve as queries e respostas brutas junto ao roteiro para auditoria. A URL externa do livro é metadado opcional, não substitui o caminho canônico.

**Não pesquise na web nem use fallback externo.** Se a API estiver indisponível, informe o impedimento. Se faltar uma passagem relevante, reformule a query ou relate a lacuna e retire a afirmação sem suporte. O forge apenas consome o acervo; não ingira livros para preencher a lacuna.

## Fluxo de trabalho

1. **Identifique o eixo temático.** Encaixe o pedido em um dos quatro eixos (ou combine dois, se fizer sentido):
   - Estoicismo → `references/estoicismo.md`
   - Autoconhecimento → `references/autoconhecimento.md`
   - Niilismo e Absurdo → `references/niilismo-absurdo.md`
   - Ética Digital e IA → `references/etica-digital-ia.md`

2. **Leia o arquivo de referência do eixo.** Use os filósofos, obras e alertas de atribuição para orientar a pesquisa; confirme no acervo as ideias que entrarão no roteiro.

3. **Defina o ângulo.** Um vídeo de 10-20 min precisa de um recorte, não de "tudo sobre estoicismo". Se o usuário deu um tema específico (ex.: "estoicismo e ansiedade"), use-o. Se veio genérico (ex.: "faz um vídeo sobre niilismo"), escolha um ângulo forte e reflexivo e informe qual foi — ofereça trocar se ele preferir.

4. **Pesquise e verifique no acervo** as ideias e citações pretendidas (ver Protocolo de Citações). Se o trecho sustenta a ideia, mas não a redação exata, use paráfrase. Se não sustenta a ideia, retire-a ou relate a lacuna.

5. **Escreva o roteiro** no tom calmo e reflexivo, montando o **JSON estruturado** conforme `references/schema-json.md`.

6. **Valide e salve.** Neste projeto, salve o JSON em `output/roteiros/<slug>.json` e rode `python src/forge/skills/conquistas-cosmicas/scripts/validar_roteiro.py <caminho>`. Toda atribuição precisa de `path` retornado pelo acervo; toda citação literal também precisa de `verificada: true` e `fonte` rastreável. Confira que o caminho existe nas respostas preservadas e que seu texto sustenta a afirmação: o validador estrutural não faz essa avaliação. Só entregue depois de passar. Apresente um link para o arquivo e um resumo curto (títulos + gancho).

7. **Revise com olhos frescos:** as citações estão corretamente atribuídas? As ideias filosóficas estão representadas com fidelidade (sem simplificação que distorce)? O texto soa bem falado em voz alta?

## Protocolo de Citações (crítico)

Modelos de linguagem inventam citações plausíveis, e a internet está cheia de frases falsamente atribuídas (sobretudo a Sêneca, Marco Aurélio, Nietzsche, Aristóteles, Sócrates). Siga estas regras:

- **Prefira ideias a frases exatas.** É quase sempre mais seguro e igualmente potente explicar o pensamento do filósofo com suas próprias palavras e atribuir a ideia à obra ("Em *Cartas a Lucílio*, Sêneca argumenta que...") do que arriscar uma citação literal.

- **Toda atribuição precisa de fonte rastreável no acervo:** nome da obra e `path` canônico copiados da resposta. Use livro, capítulo ou parágrafo apenas quando identificados na passagem ou em seus metadados.

- **Verifique antes de citar como literal.** Confirme texto e atribuição na passagem retornada pelo acervo. Muitas frases populares são apócrifas. Uma tradução própria de passagem em outro idioma entra como paráfrase, não como transcrição literal da edição.

- **Cuidado com traduções.** Os originais estão em grego, latim, alemão ou francês. Traduções variam. Ao citar, prefira uma formulação fiel ao sentido e, se relevante, sinalize que é uma tradução. Não invente uma tradução "definitiva".

- **Distinga citação de paráfrase.** Se for paráfrase, não use aspas; escreva "a ideia de Nietzsche de que..." em vez de fingir palavras exatas.

- **Respeito a direitos autorais (filósofos contemporâneos).** Autores vivos ou recentes (ex.: Byung-Chul Han, Shoshana Zuboff, Luciano Floridi) têm obras protegidas. Mantenha citações literais curtas (poucas palavras) e, na maioria das vezes, parafraseie. Autores clássicos e do século XIX (Sêneca, Marco Aurélio, Nietzsche, Kierkegaard) estão em domínio público.

- **Na dúvida, corte.** Se não dá para confirmar, não coloque entre aspas. A ideia bem explicada vale mais que uma frase de autenticidade duvidosa.

- **Verificação obrigatória antes de salvar (checklist).** Antes de finalizar o JSON, percorra o array de citações: cada item com `tipo: "literal"` precisa de `verificada: true` e de uma `fonte`. Se algum não tiver, faça a busca agora ou rebaixe para paráfrase. O validador (`scripts/validar_roteiro.py`) reprova o arquivo se essa regra for violada — rode-o e corrija antes de entregar.

- **Dados factuais atuais exigem evidência adequada.** Números e afirmações sobre o estado atual da tecnologia envelhecem rápido. Se o acervo não trouxer evidência atual e suficiente, omita-os e prefira o enquadramento filosófico atemporal. Não invente estatísticas nem consulte a web para completar o roteiro.

## Formato de saída

**A saída final é um arquivo JSON estruturado.** Monte todo o roteiro no schema descrito em `references/schema-json.md` e salve em `output/roteiros/` com um nome baseado no tema (ex.: `estoicismo-ansiedade.json`). Depois de salvar, apresente um link para o arquivo e um resumo curto e legível (os títulos e o gancho), sem despejar o JSON inteiro na conversa.

O JSON contém quatro blocos de conteúdo — os três abaixo mais um **array de citações auditável** (ver adiante), que é parte central da garantia de embasamento. Antes de salvar, rode o validador (`scripts/validar_roteiro.py`) para conferir que o schema está correto e que toda citação literal está marcada como verificada e com fonte.

As três seções de conteúdo, sempre nesta ordem dentro do JSON:

### 1. Título + gancho

- **3 opções de título** intrigantes mas honestas (sem clickbait vazio). O tom pode ser instigante; o conteúdo tem de entregar o que promete.
- **Gancho de abertura** (~15-30 segundos de narração / 40-80 palavras): uma pergunta, imagem ou tensão que faz a pessoa parar de rolar. Deve emendar direto na primeira frase do roteiro.

### 2. Roteiro de narração

Texto corrido de narração (~1.500-2.800 palavras para 10-20 min), pensado para ser **lido em voz alta**: frases de respiração natural, ritmo contemplativo, segunda pessoa ("você") para aproximar. Organize em movimentos, com marcações discretas de seção (ex.: `[ABERTURA]`, `[O PROBLEMA]`, `[O FILÓSOFO]`, `[DESENVOLVIMENTO]`, `[APLICAÇÃO]`, `[FECHAMENTO]`) para orientar a gravação e a edição.

Estrutura recomendada:
- **Abertura:** expande o gancho; conecta com uma experiência humana concreta e reconhecível.
- **O problema:** aprofunda a inquietação (ansiedade, vazio, falta de sentido, vigilância digital) de um jeito que o espectador sinta "é isso que eu vivo".
- **O(s) filósofo(s) e a ideia central:** apresenta quem pensou sobre isso, em que obra, e a ideia-chave — com fidelidade.
- **Desenvolvimento:** desdobra a ideia com citações verificadas e/ou paráfrases atribuídas, sempre explicando o que significa na prática.
- **Aplicação/reflexão:** traz a filosofia para o hoje — o que muda no modo de viver, pensar, sentir.
- **Fechamento:** amarra a jornada e termina num convite à reflexão (coerente com o tom calmo — nada de CTA agressivo). Um convite suave a comentar ou continuar pensando funciona melhor que "se inscreva agora!!!".

### 3. Sugestões de imagens/cenas

Lista mapeando trechos do roteiro a ideias visuais: B-roll, metáforas visuais, imagens cósmicas/naturais que combinam com a identidade do canal (céu estrelado, oceano, montanhas, cidade à noite, mãos, relógios, luz), e momentos para texto na tela (a citação em destaque). Indique 6-12 sugestões ancoradas em seções específicas.

### 4. Array de citações (auditável — parte da garantia de embasamento)

Todo trecho do roteiro que se apoia num filósofo entra também neste array, com campos estruturados: o texto, o autor, a obra, a referência (livro/parágrafo quando houver), o `path` canônico e o `book_id` retornados pelo acervo, o `tipo` (`"literal"` ou `"parafrase"`), se foi `verificada` (booleano) e a `fonte` (URL retornada pelo acervo, quando houver; caso contrário, o próprio caminho canônico). Regras:

- **Toda citação `"literal"` (que aparece entre aspas no roteiro) DEVE ter `verificada: true` e uma `fonte`.** Sem isso, não pode ficar entre aspas — vira paráfrase ou sai.
- Paráfrases atribuídas a uma obra têm `tipo: "parafrase"`; exigem `obra` correta e `path` presente nas evidências do acervo. Não exigem URL externa.
- Este array é a materialização do Protocolo de Citações: se uma frase não couber aqui com verificação, ela não entra como literal no roteiro.

## Tom e voz

- **Calmo e reflexivo.** Contemplativo, não apressado. Como uma conversa tarde da noite com alguém sábio e gentil.
- **Segunda pessoa, acolhedora.** Fala com o espectador, não sobre ele.
- **Imagética cósmica com moderação.** O nome do canal convida a metáforas de vastidão, estrelas, o pequeno diante do imenso — use com parcimônia para não virar clichê.
- **Sem hype barato.** Evite superlativos vazios ("essa filosofia vai MUDAR sua vida"). A profundidade vem da clareza, não do exagero.
- **Rigor sem arrogância.** Represente as ideias com fidelidade, mas de forma acessível. Se uma ideia tem nuance importante (ex.: "conhece-te a ti mesmo" não foi criada por Sócrates), inclua a nuance — ela enriquece e dá autoridade.
- **Honestidade filosófica.** Não force otimismo raso sobre temas duros. No niilismo/absurdo, por exemplo, o caminho é reconhecer o vazio e *então* mostrar a criação de sentido — não fingir que o problema não existe.

## Notas finais

- Escreva em **português do Brasil**.
- Se o pedido combinar eixos (ex.: "estoicismo na era da IA"), leia os dois arquivos de referência relevantes.
- Se faltar um dado factual ou uma citação não puder ser confirmada, prefira a formulação segura a arriscar a credibilidade do canal.
