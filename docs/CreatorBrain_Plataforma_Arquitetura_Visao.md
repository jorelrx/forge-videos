# Creator Brain Platform

> Documento de Visão, Arquitetura e Implementação

## 1. Visão do Produto

Criar uma plataforma de produção de conteúdo baseada em IA para
filosofia e desenvolvimento pessoal.

Não é um gerador de roteiros. É um sistema operacional de criação de
conteúdo.

## Objetivos

-   Pesquisa profunda
-   Memória de longo prazo
-   RAG
-   Sistema multiagentes
-   Aprendizado contínuo
-   Produção de vídeos completos

------------------------------------------------------------------------

# Fluxo Geral

``` text
Tema
  │
  ▼
Research
  │
  ▼
Knowledge Builder
  │
  ▼
Planner
  │
  ▼
Storytelling
  │
  ├── Philosophy Specialist
  ├── Psychology Specialist
  └── Scientific Specialist
          │
          ▼
Writer
  │
  ▼
Reviewer
  │
  ▼
SEO
  │
  ▼
Thumbnail
  │
  ▼
Publishing
```

# Arquitetura

``` text
                     Creator Brain
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
 Research Dept      Knowledge Dept     Creative Dept
        │                  │                  │
        ▼                  ▼                  ▼
 Search Agents     RAG + Memory        Writer Agents
        │                  │                  │
        └──────────────┬───┴──────────────┬───┘
                       ▼                  ▼
                Review Department   Publishing
```

## Departamentos

### Research

-   Busca em livros
-   Artigos científicos
-   YouTube
-   Reddit
-   Papers
-   Documentários

### Knowledge

-   Ingestão
-   Limpeza
-   Chunking
-   Embeddings
-   Catálogo
-   Versionamento

### Creative

-   Planner
-   Storytelling
-   Filosofia
-   Psicologia
-   Escrita

### Review

-   Fact checking
-   Clareza
-   Emoção
-   Retenção
-   Repetição
-   Coesão

### Publishing

-   SEO
-   Thumbnail
-   Descrição
-   Tags
-   Capítulos

# Agentes

1.  Research Agent
2.  Knowledge Builder
3.  Planner
4.  Storytelling
5.  Philosophy Agent
6.  Psychology Agent
7.  Science Agent
8.  Writer
9.  Reviewer
10. SEO
11. Thumbnail
12. Publisher

Cada agente possui: - objetivo - entrada - saída - métricas - skills -
memória temporária

# Skills

    skills/
     story/
     writing/
     youtube/
     philosophy/
     jung/
     stoicism/
     nietzsche/
     psychology/
     neuroscience/
     fact_check/
     retention/
     seo/
     thumbnail/

Cada skill contém: - regras - exemplos - critérios - boas práticas -
anti padrões

# Memória

## Longo prazo

PostgreSQL

## Vetorial

Qdrant

## Grafo

Neo4j

Tipos: - Filosófica - Psicológica - Científica - Narrativa - Performance

No Neo4j, mantenha um único grafo contendo entidades como Document, Author, Concept, Topic, Organization e Source, ligadas por relacionamentos (AUTHORED, MENTIONS, PART_OF, CITES, etc.).

# Pipeline RAG

Documentos → Chunking → Embeddings → Qdrant → Recuperação → Contexto →
Agentes

# Fluxo Editorial

Tema → Pesquisa → Planejamento → Storytelling → Escrita → Revisão →
Refatoração → SEO → Thumbnail → Aprovação → Publicação

# Estrutura sugerida

``` text
CreatorBrain/
 src/
  agents/
  workflows/
  orchestration/
  rag/
  memory/
  skills/
  prompts/
  llms/
  services/
  domain/
  infrastructure/
 config/
 docs/
 tests/
 output/
```

# Regras

-   Nunca inventar fatos.
-   Priorizar fontes primárias.
-   Sempre citar referências internamente.
-   Separar filosofia de opinião.
-   Alternar teoria e exemplos.
-   Um problema principal por vídeo.
-   Hook forte.
-   Conclusão transformadora.
-   Revisor pode reprovar qualquer etapa.

# Estrutura dos vídeos

Hook

Problema

História

Explicação

Filósofo

Psicologia

Aplicação

Resumo

Conclusão

# Aprendizado Contínuo

Registrar: - CTR - Watch Time - Retenção - Comentários - Likes -
Shares - RPM

Atualizar memória narrativa.

# Roadmap

## V1

Fundação, orquestrador, skills, múltiplos LLMs, Agentes especificos para cada tarefa.

## V2

RAG, ingestão, embeddings, banco vetorial.

## V3

Sistema multiagentes.

## V4

Aprendizado contínuo.

## V5

Produção multimídia (TTS, imagens, vídeo).

## V6

Plataforma Web completa.

# Tecnologias

-   Python
-   FastAPI
-   LangGraph
-   Pydantic AI
-   PostgreSQL
-   Qdrant
-   Neo4j
-   Redis
-   Celery ou Temporal
-   Docker
-   OpenTelemetry
-   LM Studio/OpenAI/Anthropic

# Visão Final

Construir uma plataforma capaz de transformar um único tema em um pacote
completo contendo: - pesquisa validada - base de conhecimento -
roteiro - revisão - SEO - thumbnail - publicação

com melhoria contínua baseada no desempenho real dos vídeos.
