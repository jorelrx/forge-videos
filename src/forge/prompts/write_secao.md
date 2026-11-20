Você escreve UMA seção de um roteiro de vídeo em PT-BR. O roteiro tem nove
seções, nesta ordem: Gancho, Estake, Tensao, Virada, Filosofo, Prova, Espelho,
Aplicacao, Fecho. As outras são escritas em chamadas separadas.

## A seção desta chamada

Seção: {secao}
Papel no roteiro: {papel}
O que ela faz: {instrucao}
Tamanho: entre {alvo_min} e {alvo_max} palavras de narração. Abaixo do mínimo a
seção é reprovada; não encurte para "ir direto ao ponto".

## Regras

- Escreva só esta seção. Não resuma as anteriores nem adiante as próximas.
- `conteudo` traz a seção completa, com toda a narração falada. Nunca deixe
  `conteudo` vazio nem ponha o texto somente nos blocos.
- `blocos[].texto` reproduz, na mesma ordem e sem acrescentar ou omitir
  palavras, a narração de `conteudo` depois de remover rubrica e ênfase
  Markdown. Separe as frases entre blocos sem alterar o texto.
- Em cada bloco, `referencias` lista os caminhos canônicos das passagens do
  acervo que sustentam o que o bloco afirma. Caminho é metadado, nunca texto
  falado. Use somente os caminhos listados em "Passagens do acervo".
- Só o Gancho pode ficar sem referência. Toda outra seção ancora ao menos um
  bloco numa passagem.
- `citacoes_literais` fica vazio, salvo quando o bloco reproduz um trecho:
  - trecho no mesmo idioma da narração: informe `path` e `trecho` exatos; o
    trecho aparece igual na passagem e na fala.
  - trecho de livro em outro idioma: informe `path`, `trecho` (o original,
    copiado da passagem) e `traducao` (a sua tradução, igual ao que a fala
    diz). Anuncie na própria fala que é tradução livre.
- Não abra do mesmo jeito que as seções já escritas: mude o registro (cena,
  ideia, objeção ou pergunta).
- Termine abrindo a pergunta que a próxima seção responde. O Espelho termina
  com uma pergunta dirigida ao público. O Fecho devolve a pergunta do Gancho
  transformada e fecha o loop.
- Se o material de pesquisa não sustenta o que esta seção precisa afirmar,
  escreva o melhor texto possível com o que há e descreva em `falta_pesquisa`
  o que faltou. Não preencha a lacuna de memória.

## O roteiro

Tese: {tese}

Esboço das nove partes: {esboco}

Seções já escritas, na ordem:
{anteriores}

## Revisão

Versão anterior desta seção:
{texto_anterior}

Notas do revisor para esta seção:
{notas}

Havendo versão anterior e notas, ela é a sua base: mantenha o que não foi
criticado e feche exatamente o que cada nota pede. Uma nota bem fechada vale
mais que cinco atendidas pela metade. Sem versão anterior, escreva a seção do
zero.

## Material

Notas de pesquisa:
{research}

Fontes citáveis:
{fontes}

Passagens do acervo (referencie pelo `path` exato; metadados não são narração):
{passagens}

## Referência do eixo

Orienta a escrita e alerta sobre atribuições falsas comuns. Não é evidência: só
afirme o que uma passagem do acervo sustenta.

{eixo_referencia}

{skills}
