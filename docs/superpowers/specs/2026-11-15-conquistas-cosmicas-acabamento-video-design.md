# Conquistas Cósmicas — acabamento do vídeo (frente 2)

Data: 2026-11-15. Continua
[a frente 1](2026-11-15-conquistas-cosmicas-roteiro-embalagem-design.md).

## Intenção

O roteiro e a embalagem já saem com fonte e formato de canal. O vídeo ainda
não: é uma sequência de imagens que escurece a cada ~15 segundos, sem trilha,
sem legenda e sem nada na tela que mostre de onde vem o que a narração afirma.
Esta frente faz o arquivo final parecer editado à mão e entrega, junto dele,
tudo que o upload manual pede.

Sucesso: terminada a run, o dono do canal abre a aba Publicação, baixa vídeo,
thumbnail e legenda, copia título, descrição, tags e comentário, e publica sem
abrir editor de vídeo nem de imagem.

## Objetivos

1. Transição por crossfade entre imagens; preto só na abertura e no fim.
2. Trilha sonora de uma pasta do usuário, em loop, abaixada sob a voz.
3. Narração normalizada no volume que o YouTube espera.
4. Fonte visível na tela quando a narração cita uma obra.
5. Legenda `.srt` com tempos reais, para subir no YouTube.
6. Capítulos da descrição com o tempo real do áudio.
7. Thumbnail 1280×720 pronta, com o texto desenhado por código.
8. Aba Publicação no dashboard.

## Fora do escopo

- Shorts e legenda queimada estilo Shorts (frente 4).
- Upload automático (frente 5).
- Clipes de vídeo gerados por IA e novos providers (frente 3).
- Música gerada por IA: licença para monetizar é incerta.
- Legenda palavra a palavra: exigiria ASR; o tempo por frase basta para CC.

## O que seria fracasso mesmo funcionando

- Trilha competindo com a voz, ou faixa sem licença entrando por descuido.
- Texto na tela afirmando o que nenhuma passagem do acervo sustenta.
- Vídeo com duração diferente da narração (dessincroniza legenda e capítulos).
- Run que falha por falta de trilha, fonte de letra ou embalagem: são
  acabamento, não conteúdo.

## Restrições

- `ffmpeg`/`ffprobe` continuam entrando por injeção; teste de unidade não
  codifica vídeo.
- Montagem só usa artefato catalogado, nunca varre o disco — exceto a pasta de
  trilhas, que é biblioteca do usuário e não artefato da run.
- Nenhuma chamada de modelo nova. Texto na tela e legenda saem de
  `midia.json`, `citacoes.json` e `embalagem.json`.
- Sem etapa nova no Studio (ver Abordagens).
- Nada de commit; o trabalho Codex não commitado da branch fica intacto.

## Abordagens

**A. Enriquecer as etapas que já existem (escolhida).** Montagem ganha
crossfade, trilha, cartões, legenda e capítulos reais; imagens ganha a
thumbnail. Nada muda em `StageName`, migrações, worker ou ordem de etapas do
painel. Custo: `montagem.py` cresce, então a lógica nova mora em módulos
próprios e o executor só orquestra.

**B. Etapa nova `acabamento` depois da montagem.** Isola o risco, mas toca o
enum de etapas, a migração do banco, a máquina de estados, o worker e o painel
— e re-encoda o vídeo uma segunda vez, perdendo qualidade e minutos.

**C. Script de pós-produção fora do Studio.** Mais barato, mas o resultado não
entra no catálogo, não aparece no painel e não tem gate.

A ganha porque o acabamento é parte de montar o vídeo, e porque B paga uma
migração para separar o que roda no mesmo `ffmpeg`.

## Desenho

### 1. Ritmo: crossfade ([executors/ffmpeg.py](../../../src/forge/executors/ffmpeg.py))

- Cada clipe é renderizado sem fade próprio e com `CROSSFADE` (0,6 s) a mais
  de duração; o último não leva o acréscimo.
- Um passe único encadeia `xfade` com o corte de cada transição no fim da
  duração nominal acumulada. A linha do tempo fica igual à soma das durações
  nominais, que é a duração da narração: capítulos e legenda continuam valendo.
- Fade de preto só no início do primeiro clipe e no fim do último.
- Beat mais curto que duas vezes o crossfade entra em corte seco.

### 2. Áudio: trilha e volume (novo `services/trilha.py`, `executors/ffmpeg.py`)

- Pasta `FORGE_TRILHAS_DIR` (padrão `library/trilhas`). Extensões: mp3, wav,
  flac, ogg, m4a. Se existir subpasta com o nome do eixo do vídeo, ela tem
  preferência; senão a raiz.
- Escolha determinística: hash do id da run sobre a lista ordenada. Repetir a
  etapa escolhe a mesma faixa.
- Mixagem: narração normalizada a −14 LUFS (`loudnorm`); trilha em loop, com
  fade de entrada de 2 s e de saída de 4 s, abaixada pela narração com
  `sidechaincompress`; volume-base da trilha em `FORGE_TRILHA_VOLUME_DB`
  (padrão −20).
- Crédito: arquivo `<faixa>.txt` ao lado da faixa, se existir, tem a linha de
  atribuição. Ela entra na descrição como `Música: ...`.
- Pasta ausente ou vazia: vídeo sai só com a narração, com aviso
  `trilha_ausente` no gate (não reprova).
- `video/narration.wav` continua sendo a narração pura: a validação mede
  silêncio e coerência de duração nela.

### 3. Linha do tempo (novo `services/linha_tempo.py`)

Uma função única devolve, para cada bloco de narração, início e fim em
segundos a partir da duração real dos WAVs. Cartões, legenda e capítulos leem
dela — três consumidores, uma conta.

### 4. Cartões de fonte (novo `services/cartoes.py`)

Gera `video/cartoes.ass`, queimado no passe final com o filtro `ass`.

- **Paráfrase:** faixa discreta no rodapé, `Autor — Obra`, por até 6 s a
  partir do início do bloco. Aparece quando a obra muda ou na primeira citação
  de cada seção — não a cada bloco (na última run real seriam 18 vezes William
  James).
- **Literal ou tradução:** o trecho falado inteiro, centralizado sobre fundo
  escurecido, com `Autor — Obra` embaixo, pela duração do bloco. Tradução leva
  a marca `tradução livre`. Acima de 220 caracteres cai para a faixa de rodapé.
- O texto vem só de `citacoes.json`. Bloco sem citação não ganha cartão.
- Sem `citacoes.json` (run antiga): nenhum cartão, sem falha.
- Fonte de letra: `FORGE_FONTE_VIDEO` (padrão `Georgia`, presente no Windows).

### 5. Legenda (novo `services/legendas.py`)

`video/legendas.srt`, artefato `legendas.srt`.

- Uma ou mais deixas por frase do bloco, sem tags de TTS nem rubrica.
- Tempo dentro do bloco repartido pela contagem de caracteres.
- Deixa com no máximo duas linhas de 42 caracteres; frase maior é quebrada em
  vírgula ou espaço. Duração mínima de 1 s; tempos crescentes e sem
  sobreposição.

### 6. Capítulos com tempo real ([agents/embalagem.py](../../../src/forge/agents/embalagem.py))

- Início do capítulo = início do primeiro bloco da seção, arredondado.
- A montagem regrava `video/embalagem.json` e `embalagem.md` com
  `capitulos_estimados = false`, a linha de música (se houver) e a descrição
  remontada.
- Capítulo que ficar com menos de 10 s é fundido no anterior: perder um
  marcador é melhor que o YouTube ignorar todos.
- Sem `embalagem.json`: passo pulado.

### 7. Thumbnail (etapa imagens, novo `services/thumbnail.py`)

- Item extra na etapa de imagens, chave `thumbnail`, prompt de
  `embalagem.thumbnail.prompt` mais o estilo visual do canal. A base é
  catalogada com tipo próprio, para não ser lida como imagem de beat nem cair
  no gate de 1024×576.
- Composição por código (Pillow): redimensiona e corta para 1280×720, escurece
  em gradiente o lado do texto, desenha `embalagem.thumbnail.texto` em até duas
  linhas, letra grande com contorno. Saída `video/thumbnail.jpg`.
- Gate: 1280×720 e menos de 2 MB; qualidade JPEG desce até caber.
- Fonte de letra: `FORGE_FONTE_THUMBNAIL` (padrão Georgia negrito do Windows).
  Arquivo ausente: aviso, thumbnail sai sem texto.
- Sem `embalagem.json`: item não é planejado.

### 8. Aba Publicação (web, API)

- Item novo na navegação. Mostra a run concluída mais recente, com seletor
  para outras.
- Conteúdo: os três títulos, descrição, tags (separadas por vírgula) e
  comentário fixado, cada um com botão copiar e contador de caracteres;
  thumbnail; botões para baixar vídeo, thumbnail e legenda; aviso quando os
  capítulos ainda são estimados.
- Lista de conferência do upload manual: thumbnail, legenda em português,
  capítulos na descrição, comentário fixado, declaração de conteúdo sintético.
- API: sem rota nova. A aba lê `embalagem.json` pelo conteúdo do artefato. O
  tipo `.srt` entra na lista de tipos servidos.

### Gates da montagem

Reprovam: os de hoje, mais legenda ausente ou com tempo fora de ordem, e
duração do vídeo diferente da narração além da tolerância atual.

Avisos: `trilha_ausente`, `cartoes_ausentes`, `capitulos_estimados`.

## Configuração nova

| Variável | Padrão |
|---|---|
| `FORGE_TRILHAS_DIR` | `library/trilhas` |
| `FORGE_TRILHA_VOLUME_DB` | `-20` |
| `FORGE_CROSSFADE_SEGUNDOS` | `0.6` |
| `FORGE_FONTE_VIDEO` | `Georgia` |
| `FORGE_FONTE_THUMBNAIL` | `C:\Windows\Fonts\georgiab.ttf` |

Todas entram no hash de entrada da etapa que afetam.

## Verificação

- Unidade: linha do tempo, escolha de trilha, cartões, legenda, capítulos,
  thumbnail e a sequência de comandos do `ffmpeg`, com runner injetado.
- Um teste real de `ffmpeg`, marcado e pulado quando o binário falta: três
  imagens e três WAVs sintéticos, conferindo duração, faixa de áudio e que o
  quadro do meio de uma transição não é preto.
- Web: testes de componente da aba.
- Run real completa (TTS na RX 580 e cota de imagem) só com o seu aval, no fim.

## Deixado ao construtor

- Estilo exato dos cartões e da thumbnail (tamanho, margem, opacidade), dentro
  do tom calmo do canal.
- Parâmetros do compressor da trilha.
- Divisão do passe final em mais de um comando se o encadeamento de `xfade`
  com dezenas de entradas se mostrar instável.
