# Schema JSON do Roteiro

A saída da skill é um arquivo JSON com esta estrutura. No forge-videos, salve em `output/roteiros/<slug-do-tema>.json` e valide com `python src/forge/skills/conquistas-cosmicas/scripts/validar_roteiro.py <caminho>` antes de entregar. As referências devem vir exclusivamente da API do acervo (`FORGE_ACERVO_URL`, padrão `http://127.0.0.1:8000`).

Os campos `path` e `book_id` de cada citação devem ser copiados de uma passagem efetivamente retornada pela API. Não invente esses valores a partir de obra, capítulo ou autor. O exemplo abaixo ilustra apenas o formato; seus marcadores não são fontes verificadas e não podem ser usados num roteiro final.

## Estrutura

```json
{
  "meta": {
    "canal": "Conquistas Cósmicas",
    "eixo": "estoicismo",
    "tema": "estoicismo e ansiedade",
    "duracao_estimada_min": "12-15",
    "gerado_em": "2026-07-17"
  },
  "titulos": [
    "A ansiedade mora no futuro — e você não precisa morar lá",
    "O que os estoicos sabiam sobre a mente ansiosa (e nós esquecemos)",
    "A pergunta de 2000 anos que silencia a ansiedade"
  ],
  "gancho": {
    "duracao_seg": 20,
    "texto": "Repare numa coisa estranha: quase nunca a ansiedade fala do agora..."
  },
  "roteiro": [
    { "secao": "ABERTURA", "texto": "..." },
    { "secao": "O PROBLEMA", "texto": "..." },
    { "secao": "A IDEIA CENTRAL", "texto": "..." },
    { "secao": "DESENVOLVIMENTO", "texto": "..." },
    { "secao": "APLICAÇÃO", "texto": "..." },
    { "secao": "FECHAMENTO", "texto": "..." }
  ],
  "citacoes": [
    {
      "texto": "Não perca mais tempo discutindo o que um bom homem deveria ser. Seja um.",
      "autor": "Marco Aurélio",
      "obra": "Meditações",
      "referencia": "Livro 10.16",
      "path": "<copiar Passagem.path da resposta do acervo>",
      "book_id": 0,
      "tipo": "literal",
      "verificada": true,
      "fonte": "<copiar Passagem.url ou Passagem.path da resposta do acervo>"
    },
    {
      "texto": "Não são os acontecimentos que perturbam as pessoas, mas os juízos que fazem sobre eles.",
      "autor": "Epicteto",
      "obra": "Encheirídion",
      "referencia": "5",
      "path": "<copiar Passagem.path da resposta do acervo>",
      "book_id": 0,
      "tipo": "parafrase",
      "verificada": true,
      "fonte": ""
    }
  ],
  "cenas": [
    { "secao": "GANCHO", "sugestao": "Pessoa imóvel numa sala tranquila enquanto imagens caóticas de cenários futuros passam em sobreposição." },
    { "secao": "O PROBLEMA", "sugestao": "Mão tentando segurar água escorrendo — o incontrolável." }
  ],
  "contagem_palavras_roteiro": 2100
}
```

## Campos

### `meta` (objeto, obrigatório)
- `canal` (string): sempre `"Conquistas Cósmicas"`.
- `eixo` (string): um de `"estoicismo"`, `"autoconhecimento"`, `"niilismo-absurdo"`, `"etica-digital-ia"`. Se combinar eixos, use o principal e mencione o secundário no tema.
- `tema` (string): o recorte específico do vídeo.
- `duracao_estimada_min` (string): faixa estimada, ex.: `"12-15"`.
- `gerado_em` (string): data no formato `AAAA-MM-DD`.

### `titulos` (array de strings, obrigatório)
Exatamente 3 opções de título.

### `gancho` (objeto, obrigatório)
- `duracao_seg` (número): estimativa entre ~15 e ~30.
- `texto` (string): 40-80 palavras; emenda direto na primeira seção do roteiro.

### `roteiro` (array de objetos, obrigatório)
Cada item: `{ "secao": <string em CAIXA ALTA>, "texto": <string> }`. A soma dos textos deve ficar entre ~1.500 e ~2.800 palavras (10-20 min). Seções sugeridas: ABERTURA, O PROBLEMA, A IDEIA CENTRAL / O FILÓSOFO, DESENVOLVIMENTO, APLICAÇÃO, FECHAMENTO (adapte conforme o tema).

### `citacoes` (array de objetos, obrigatório)
Cada item:
- `texto` (string): a frase citada ou parafraseada.
- `autor` (string).
- `obra` (string): nome da obra — obrigatório e correto.
- `referencia` (string): livro/carta/parágrafo quando houver; pode ser `""`.
- `path` (string, obrigatório): caminho canônico copiado de `Passagem.path`, inclusive para paráfrases. Precisa existir nas respostas brutas preservadas da pesquisa.
- `book_id` (inteiro): identificador copiado de `Passagem.book_id`.
- `tipo` (string): `"literal"` ou `"parafrase"`.
- `verificada` (booleano).
- `fonte` (string): `Passagem.url` quando houver, ou o próprio `Passagem.path`. **Obrigatória e não vazia quando `tipo` = `"literal"`.** Não pesquise uma URL externa para completar este campo.

Regras estruturais: toda citação precisa de `path` não vazio; todo item `"literal"` também precisa de `verificada: true` e `fonte` não vazia. Além do validador, confira que o caminho está na pesquisa preservada e que a passagem sustenta o texto atribuído.

### `cenas` (array de objetos, obrigatório)
6-12 itens, cada um `{ "secao": <string>, "sugestao": <string> }`, ancorados em seções do roteiro.

### `contagem_palavras_roteiro` (número, obrigatório)
Total de palavras somando os textos de `roteiro`.
