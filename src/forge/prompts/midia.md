Você vai preparar a produção de um vídeo a partir do roteiro abaixo.

Tema: {tema}
Tese: {tese}

Roteiro:

{roteiro}

Duas listas.

**Blocos de narração.** Fatie o roteiro inteiro, na ordem, em trechos de 1 a 3
frases. Nenhuma palavra do roteiro pode ser perdida ou reescrita — você está
cortando, não editando. Cada bloco registra de qual seção veio.

Cada bloco pode começar com tags de controle de voz, e usar pausas no meio.
Use-as com parcimônia: só onde a leitura muda de verdade.

- emoção: `<|emotion:contemplation|>`, `<|emotion:awe|>`, `<|emotion:bitterness|>`,
  `<|emotion:determination|>`, `<|emotion:sadness|>`, `<|emotion:surprise|>`
- ritmo: `<|prosody:speed_slow|>`, `<|prosody:speed_fast|>`,
  `<|prosody:pitch_low|>`, `<|prosody:expressive_high|>`
- pausa, no meio do texto: `<|prosody:pause|>`, `<|prosody:long_pause|>`

Não invente tag fora dessa lista.

**Beats visuais.** Uma imagem a cada {alvo_segundos} segundos de narração
aproximadamente — conte cerca de 15 palavras por 5 segundos. Cada beat aponta o
bloco em que a imagem entra e traz o prompt de geração, em inglês, concreto e
visual: cena, luz, composição, atmosfera. Nada de texto na imagem, nada de
rosto de pessoa real, nada abstrato demais para desenhar.

Os ids que você escrever são renumerados depois, então a forma exata deles não
importa — mas eles precisam ser distintos entre si dentro da sua lista de
blocos, porque `bloco_id` é resolvido através deles: um id repetido faz o beat
apontar para o bloco errado.
