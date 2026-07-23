# Camada Knowledge

O sistema deve transformar texto bruto em **conhecimento estruturado, validado e conectado**.

A arquitetura utilizada será inspirada em como um pesquisador humano estuda um livro.

```text
Livro
    ↓
Leitura
    ↓
Compreensão
    ↓
Extração de conhecimento
    ↓
Organização
    ↓
Relacionamento
    ↓
Comparação com outros livros
    ↓
Refinamento
    ↓
Memória de longo prazo
```

Em vez de salvar apenas pedaços de texto, o sistema cria vários níveis de representação do conhecimento.

---

# Os 6 níveis da Base de Conhecimento

Eu dividiria a base em seis camadas independentes.

```text
Nível 1
Documento Original

↓

Nível 2
Chunks

↓

Nível 3
Conhecimento Estruturado

↓

Nível 4
Relações

↓

Nível 5
Conceitos Refinados

↓

Nível 6
Conhecimento Global
```

Cada nível possui objetivos diferentes.

---

# Nível 1 — Documento Original

Nunca altere o texto.

Guarde exatamente como veio.

```text
Livro

Autor

Idioma

Edição

Capítulo

Página

ISBN

Fonte

URL

Licença

Hash

Data
```

Esse nível é a "fonte da verdade".

---

# Nível 2 — Chunking Inteligente

O erro da maioria dos sistemas é cortar texto por quantidade de tokens.

Eu faria um pipeline semântico.

```text
Livro

↓

Capítulo

↓

Subcapítulo

↓

Seção

↓

Ideia

↓

Argumento

↓

Parágrafo

↓

Sentenças
```

Cada chunk conhece:

```text
Pai

Filhos

Capítulo

Página

Contexto

Resumo

Tema

Conceitos
```

Assim um trecho nunca perde contexto.

---

# Nível 3 — Estudo do Chunk

Agora entra a IA.

Cada chunk passa por diversos agentes especializados.

```text
Chunk

↓

Agente de Resumo

↓

Agente de Conceitos

↓

Agente de Entidades

↓

Agente Filosófico

↓

Agente Histórico

↓

Agente de Palavras-chave

↓

Agente de Citações
```

Cada agente gera uma visão diferente.

Exemplo:

Chunk:

> "O homem está condenado à liberdade."

O sistema produz:

Resumo

```text
Sartre afirma que a liberdade é inevitável e implica responsabilidade.
```

Conceitos

```text
Liberdade

Responsabilidade

Existencialismo

Escolha
```

Entidades

```text
Jean-Paul Sartre
```

Categoria

```text
Existencialismo
```

Tipo

```text
Afirmação Filosófica
```

---

# Nível 4 — Extração de Conhecimento

Agora começa o verdadeiro estudo.

O texto vira fatos.

Exemplo:

Texto

```text
A coragem nasce do enfrentamento do medo.
```

Transforma em:

```text
Conceito

Coragem

↓

Relaciona-se

↓

Medo

Tipo

Superação
```

Outro exemplo

```text
Nietzsche critica a moral cristã.
```

Vira

```text
Nietzsche

CRITICA

Moral Cristã
```

---

# Ontologia

Tudo segue uma ontologia.

```text
Pessoa

Livro

Conceito

Escola Filosófica

Argumento

Teoria

Evento Histórico

Citação

Pergunta

Resposta
```

---

# Extração de Afirmações

Cada frase pode virar uma proposição.

```text
"O sofrimento fortalece."

↓

Sujeito

Sofrimento

↓

Relação

Fortalece

↓

Objeto

Indivíduo
```

Essas afirmações ficam no Neo4j.

---

# Argumentos

Outra camada muito importante.

```text
Premissa 1

↓

Premissa 2

↓

Conclusão
```

Exemplo

```text
Todos morrem.

Sócrates é homem.

↓

Logo

↓

Sócrates morre.
```

Isso permite raciocínio.

---

# Contra-argumentos

O sistema procura automaticamente.

```text
Livro A

↓

Afirma

↓

Livre Arbítrio existe

Livro B

↓

Afirma

↓

Livre Arbítrio é ilusão
```

Neo4j

```text
CONTRADIZ
```

---

# Similaridade Conceitual

Depois do embedding tradicional...

Cada conceito recebe embedding próprio.

Não apenas o chunk.

```text
Chunk

↓

Conceitos

↓

Embedding
```

Exemplo

Chunk

```text
Virtude
```

Embedding próprio.

Chunk

```text
Ética
```

Outro embedding.

Isso melhora absurdamente a recuperação.

---

# Grafo Hierárquico

```text
Livro

↓

Capítulo

↓

Seção

↓

Argumento

↓

Conceito

↓

Palavra-chave
```

---

# Refinamento entre Livros

Agora vem uma etapa que quase nenhum sistema implementa.

Depois que um livro termina...

Ele é comparado com toda a base.

```text
Livro Novo

↓

Busca conceitos iguais

↓

Busca autores iguais

↓

Busca escolas iguais

↓

Busca temas iguais

↓

Busca argumentos iguais

↓

Busca contradições

↓

Atualiza Neo4j
```

---

# Descoberta de Novos Relacionamentos

Exemplo

Livro A

```text
Estoicismo
```

Livro B

```text
Marco Aurélio
```

Livro C

```text
Virtude
```

O sistema cria

```text
Marco Aurélio

PERTENCE

Estoicismo

↓

DEFENDE

Virtude
```

Mesmo que isso esteja distribuído entre livros diferentes.

---

# Refinamento por Confiança

Cada afirmação recebe uma pontuação.

```text
Livro

↓

Afirmação

↓

Confiança
```

Exemplo

Encontrada em

1 livro

```text
0.35
```

Encontrada em

15 livros

```text
0.92
```

Encontrada em Stanford Encyclopedia

```text
0.99
```

---

# Memória Global

Depois de milhares de livros.

O sistema cria uma memória própria.

Exemplo

```text
Virtude

↓

Aristóteles

↓

Estoicismo

↓

Ética

↓

Felicidade

↓

Excelência Moral

↓

Razão
```

Isso não veio de um único livro.

Veio da base inteira.

---

# Geração Automática de Resumos

Depois de muitos livros.

```text
Estoicismo

↓

100 livros

↓

Resumo Global

↓

Principais ideias

↓

Autores

↓

Diferenças

↓

Evolução histórica
```

Isso fica salvo.

---

# Geração de Conhecimento de Alto Nível

Além de armazenar informações, o sistema pode produzir **artefatos derivados** que também passam a integrar a base:

* **Síntese por conceito**: consolida tudo o que a base conhece sobre um conceito (por exemplo, "virtude"), citando diferentes autores e épocas.
* **Linha do tempo intelectual**: organiza como uma ideia evoluiu historicamente.
* **Mapa de escolas filosóficas**: identifica convergências, divergências e influências.
* **Perguntas e respostas canônicas**: gera respostas fundamentadas, sempre apontando para as evidências originais.
* **Lacunas de conhecimento**: detecta conceitos com pouca cobertura ou relações pouco exploradas, ajudando a decidir quais livros estudar em seguida.

---

# Fluxo completo de estudo

```text
Livro
   │
   ▼
Aquisição e validação
   │
   ▼
Extração do texto preservando a estrutura
   │
   ▼
Normalização e limpeza
   │
   ▼
Chunking semântico hierárquico
   │
   ▼
Análise por agentes especializados
   │
   ├── Resumo
   ├── Conceitos
   ├── Entidades
   ├── Argumentos
   ├── Citações
   ├── Eventos
   ├── Palavras-chave
   └── Classificação temática
   │
   ▼
Extração de fatos e proposições
   │
   ▼
Geração de embeddings (chunks, conceitos e relações)
   │
   ▼
Deduplicação e consolidação
   │
   ▼
Comparação com toda a base existente
   │
   ▼
Criação e atualização do grafo de conhecimento
   │
   ▼
Geração de sínteses e conhecimento global
   │
   ├── Qdrant (busca semântica)
   ├── Neo4j (relações e raciocínio)
   ├── Banco relacional (estado, versões e metadados)
   └── Base de resumos e sínteses
```
