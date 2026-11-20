# Conquistas Cósmicas — roteiro de canal e embalagem (frente 1 de 5)

Data: 2026-11-15. Estado: aguardando aprovação.

## Intenção

O forge passa a produzir vídeos para um canal específico, o **Conquistas
Cósmicas**: filosofia reflexiva em PT-BR, 10 a 20 minutos, narrada, com o
objetivo de ganhar visualizações e monetizar. Hoje o pipeline entrega um roteiro
genérico de ~1.200 palavras e nenhum material de publicação. Esta frente faz o
roteiro nascer com a identidade e as técnicas de retenção do canal, e faz cada
run entregar também a embalagem que decide o clique: títulos, conceito de
thumbnail, descrição com fontes e capítulos, tags e comentário fixado.

A regra herdada da skill `conquistas-cosmicas` continua inegociável: **nenhuma
afirmação sem passagem do acervo**. A credibilidade é o diferencial do canal e
também a defesa contra a política de "conteúdo inautêntico" do YouTube, que
desmonetiza produção em massa sem valor próprio.

## Ordem das frentes

1. **Roteiro de canal + embalagem** — este documento.
2. Qualidade do vídeo: trilha, legendas, cartões de citação, ritmo de imagem,
   thumbnail renderizada, capítulos com tempo real do áudio.
3. Providers das assinaturas Claude e Google.
4. Shorts.
5. Publicação (upload fica manual até pedido em contrário).

## Objetivos

- Roteiro de 1.600 a 2.450 palavras (≈ 11 a 16 min a 150 palavras/min).
- Voz do canal: segunda pessoa ("você"), calma, contemplativa, sem hype.
- Técnicas de retenção escritas como regra e conferidas por gate.
- Tema escolhido com base no que o acervo sustenta e no que o público procura.
- Citações auditáveis num artefato próprio, derivado por código.
- Embalagem pronta para colar no YouTube Studio.

## Fora do escopo desta frente

- Renderizar a thumbnail (PNG) e recalcular capítulos pelo áudio real: frente 2.
- Botão "sugerir tema" no dashboard. No Studio o tema continua obrigatório;
  `forge temas` imprime sugestões para colar lá.
- Novos providers, upload, Shorts.
- Abstração multi-canal. O projeto serve a um canal; a identidade entra pelos
  mecanismos que já existem (skills e prompts em markdown).
- Reproduzir o JSON de `references/schema-json.md`. Os artefatos tipados do
  forge cobrem os mesmos dados com garantia mais forte.

## Anti-objetivos

- Título ou thumbnail que prometa o que o roteiro não entrega.
- Qualquer caminho que deixe texto sem fonte passar para compensar acervo ralo.
- CTA agressivo ("inscreva-se agora", "deixe o like") no meio do vídeo.
- Roteiros que soem todos iguais: a estrutura é fixa, a abertura e o exemplo de
  cada vídeo não.

## Restrições

- Acervo atual: 39 livros (Nietzsche, Kierkegaard, Platão, Kant, Taoismo,
  Dhammapada, Darwin, William James, livre-arbítrio). Não há estoicos, Camus nem
  autores de ética digital: dois dos quatro eixos ficam sem tema até o projeto
  `research` ingerir essas obras. O forge não ingere nada.
- Os livros estão em inglês, alemão e chinês; o roteiro é em português. Citação
  literal exige o trecho idêntico na passagem, logo quase toda citação é
  tradução própria.
- O contrato das nove seções (`SECOES_NOMES`) é lido por artefatos, retomada,
  gates, plano de mídia e Studio. Não muda.
- O branch tem mudanças não commitadas de outra frente (Codex OAuth). O trabalho
  entra por cima, sem commitar nem reverter o que já está lá.
- Testes continuam com modelo simulado e sem rede.

## Abordagens consideradas

**A. Manter as nove seções, alongá-las e escrever seção por seção (escolhida).**
O contrato fechado fica intacto; `escrever()` passa a fazer uma chamada por
seção, cada uma com seu papel, alvo de palavras e as seções anteriores como
contexto. Rodadas de revisão reescrevem só as seções citadas nas notas. Custa
nove chamadas no primeiro rascunho em vez de uma.

**B. Manter a chamada única e só subir os alvos.** Menor mudança. Mas uma
chamada teria de emitir ~2.000 palavras duas vezes (`conteudo` e `blocos`
idênticos): modelos encurtam texto longo pedido de uma vez e a conferência
palavra por palavra entre os dois campos falha mais. Além disso, hoje o
`write` de revisão nem recebe o roteiro anterior — regenera tudo com as notas.

**C. Adotar o schema da skill (seis seções + array de citações) como contrato.**
Fiel à skill, mas quebra tudo que depende dos nove nomes para ganhar pouco:
`blocos[].referencias` já é auditoria de citação mais forte que o array.

Escolha: **A**. É a única que atinge a duração com confiabilidade e ainda
conserta a revisão dirigida. Decisão minha; o usuário delegou o "como".

## Desenho

### 1. Identidade do canal

- Nova skill `skills/canal.md` (dono `write`): voz, tom, imagética cósmica com
  parcimônia, honestidade filosófica, o que o canal nunca faz. Conteúdo vem do
  bloco "Tom e voz" e do "Protocolo de Citações" da skill original.
- `skills/writing.md`: troca "primeira pessoa" por segunda pessoa e ritmo de
  fala. `skills/retention.md`: reescrita com as técnicas abaixo.
- `plan`, `write` e `review` carregam `canal`.
- Os quatro arquivos em `skills/conquistas-cosmicas/references/` viram dados do
  pipeline. `Plano` ganha `eixo` (um dos quatro, ou nenhum); o state carrega
  `eixo`; `write` e `review` recebem a referência do eixo, com o aviso de que
  ela orienta e alerta sobre atribuições falsas, mas não é evidência.
- `SKILL.md` e `scripts/validar_roteiro.py` ficam como estão; o pipeline não os lê.

### 2. Técnicas de retenção (regra + gate)

| Técnica | Onde vira regra | Conferência determinística |
|---|---|---|
| Gancho entra numa cena ou tensão dirigida a "você", sem saudação nem "neste vídeo" | `retention.md`, instrução do Gancho | grave: abertura com saudação/preâmbulo |
| Promessa do que o espectador leva, sem entregar | instrução do Gancho | — (revisor) |
| Loop aberto no Gancho, pago só no Fecho | já existe | aviso existente |
| Cada seção termina abrindo a pergunta da próxima | `retention.md` | — (revisor) |
| Troca de registro a cada seção: cena, ideia, objeção, pergunta | `retention.md`, `story.md` | grave existente: aberturas parecidas |
| Concreto antes do abstrato; um exemplo nomeado por seção | `writing.md` | — (revisor) |
| Objeção forte tratada pelo melhor lado | instrução de Filosofo/Prova | — (revisor) |
| Prática para hoje na Aplicacao | instrução da Aplicacao | — (revisor) |
| CTA suave: pergunta no Espelho, convite no Fecho | `canal.md` | aviso: termos de CTA agressivo fora do Fecho; grave existente: Espelho termina em pergunta |
| Frase falável | `writing.md` | grave existente: frase > 40 palavras |

### 3. Arquitetura longa

Alvos novos por seção em `ARQUITETURA` (mínimo–máximo de palavras): Gancho
60–110, Estake 130–220, Tensao 180–280, Virada 180–280, Filosofo 260–380,
Prova 280–400, Espelho 180–280, Aplicacao 220–320, Fecho 110–180. Soma
1.600–2.450.

Gates: mantém a regra por seção (grave abaixo de 60% do mínimo, aviso acima de
160% do máximo) e acrescenta o total — grave abaixo de 1.500 palavras, aviso
acima de 2.800.

### 4. Escrita por seção

- `escrever()` mantém a assinatura e o retorno. Sem notas: percorre
  `ARQUITETURA` em ordem; cada chamada usa o novo prompt `write_secao.md` com
  tese, esboço, papel/instrução/alvo da seção, as seções já escritas, passagens,
  referência do eixo e skills. Devolve uma seção com `conteudo`, `blocos` e
  `falta_pesquisa`. As validações atuais (blocos reproduzem a narração,
  referências existem, trecho literal confere) rodam por seção.
- Com notas: `Nota` ganha `secao` opcional; o revisor é instruído a preenchê-la.
  Só as seções citadas são reescritas, recebendo o texto anterior e suas notas;
  as demais passam intactas. Nota sem seção vale para todas. Para isso `write`
  passa a ler `roteiro` do state.
- `falta_pesquisa`: o roteiro sempre sai completo; o primeiro pedido encontrado
  dispara o handoff para `research`, como hoje.
- `prompts/write.md` é substituído por `write_secao.md`.

### 5. Citações

- `CitacaoLiteral` ganha `traducao` opcional. Com `traducao`: `trecho` (idioma
  original) tem de estar na passagem e `traducao` tem de estar no texto do
  bloco. O roteiro anuncia a tradução na fala ("em tradução livre"). Sem
  `traducao`, vale a regra atual.
- O revisor confere a fidelidade da tradução contra o trecho original.
- Novo `video/citacoes.json`, derivado por código de `blocos` + passagens: para
  cada referência, autor, obra, `path`, `book_id`, URL quando o acervo der,
  tipo (`literal`, `traducao`, `parafrase`), texto e seção. Nenhuma chamada de
  modelo. Alimenta a descrição agora e os cartões de citação na frente 2.

### 6. Seletor de tema

Novo `agents/tema.py::sugerir_temas(model, acervo, settings, n)`:

1. Lê os livros do acervo (`GET /books`, método novo `Acervo.livros()`), os ângulos dos quatro eixos e os temas
   já feitos (`output/roteiros/*.md` e `output/runs/*/video/input.json`).
2. Uma chamada propõe candidatos: tema, eixo, dor do espectador, promessa e duas
   buscas no idioma dos livros.
3. Código roda as buscas no acervo e junta as passagens por candidato.
4. Uma chamada julga, com os trechos na mão, quais candidatos o acervo sustenta
   de fato e os ordena por apelo ao público. Candidato sem sustentação sai.

`forge temas [--n 5]` imprime a lista com os livros que sustentam cada tema e os
eixos sem cobertura. `forge roteiro` sem `--tema` usa o primeiro. Sem nenhum
candidato sustentado, falha com mensagem clara — não inventa tema.

### 7. Embalagem

Novo `agents/embalagem.py`, executado só com roteiro aprovado, junto do plano de
mídia (CLI: depois de `_plano_de_midia`; Studio: dentro da etapa `plano_midia`,
sem etapa nova). Entrada: tese + roteiro aprovado + `citacoes.json`. Nada de
pesquisa nova, para não nascer afirmação fora do roteiro.

O modelo propõe: três títulos com o ângulo de cada um, texto e prompt da
thumbnail, duas linhas de abertura da descrição, resumo, rótulo de capítulo por
seção, tags e hashtags. O código monta o resto:

- **Capítulos:** tempo estimado pela contagem de palavras (150/min), marcados
  como estimados.
- **Fontes da descrição:** de `citacoes.json`.
- **Comentário fixado:** a pergunta final do Espelho.
- **Aviso de IA** ao fim da descrição (`FORGE_AVISO_IA`, ligado por padrão).

Gates (graves): exatamente três títulos distintos, cada um ≤ 70 caracteres e sem
caixa alta gritada; texto da thumbnail com 1 a 4 palavras e diferente dos
títulos; capítulos começando em 00:00, ao menos três, cada um ≥ 10 s; descrição
≤ 5.000 caracteres com primeira linha ≤ 150; tags ≤ 500 caracteres no total; até
três hashtags. Reprovou: uma nova chamada com os achados; reprovou de novo, a
etapa falha (no CLI, registra o erro e mantém o roteiro entregue).

Saídas: `video/embalagem.json` e `embalagem.md` na raiz da run, registrados no
catálogo do Studio.

## Decisões minhas, para conferência

- Alvo de 11 a 16 minutos (dentro dos 10–20 da skill; acima de 8 min libera
  anúncio no meio do vídeo).
- Citação traduzida entra como tipo próprio e é anunciada na fala.
- Aviso de IA na descrição, ligado por padrão.
- Capítulos são estimados nesta frente; o tempo real vem na frente 2.
- No Studio, tema continua obrigatório.
- `fluxos.py` (experimento não commitado, com nomes indefinidos) não é tocado.

## Deixado para quem implementa

- Texto final das skills e dos prompts, dentro das regras acima.
- Lista exata de saudações, preâmbulos e termos de CTA dos gates.
- Como persistir `eixo` no artefato do plano de modo que `--retomar` o leia.
- Ajuste dos testes existentes que montam roteiros curtos.
- Atualização do `CLAUDE.md` do projeto.

## Verificação

- `uv run pytest` verde, com testes novos para: alvos e gate de total, escrita
  por seção e revisão dirigida, citação traduzida, `citacoes.json`, seletor de
  tema, embalagem e seus gates.
- Uma run real com o provider atual (`codex`, `gpt-6.1-sol`) e o acervo local,
  conferindo contagem de palavras, `citacoes.json` e `embalagem.md`.
