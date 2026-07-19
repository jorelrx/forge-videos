# Sistema de Logging do Forge

Este projeto utiliza `structlog` com `logging` padrão do Python para logs estruturados e coloridos.

## Configuração Padrão

- **Formato**: `%asctime [levelname] name - message`
- **Timestamp**: ISO 8601
- **Níveis**: DEBUG, INFO, WARNING, ERROR
- **Output**: Console (stderr) com cor codificada por nível

## Exemplos de Uso

```python
from forge.logging import get_logger

logger = get_logger("my.module")

# Log simples
logger.info("Operação realizada", parametro="valor")

# Log com exceto
try:
    # ... código que pode falhar
except Exception as e:
    logger.error("Erro crítico", error=str(e), exc_info=True)

# Log de debug (somente quando log_level <= DEBUG)
logger.debug("Detalhes internos", detalhe1="valor1")
```

## Níveis de Log no CLI

No arquivo `.env`, configure `FORGE_LOG_LEVEL`:

```bash
FORGE_LOG_LEVEL=DEBUG  # Verbose (todos os logs)
FORGE_LOG_LEVEL=INFO   # Padrão (apenas informações importantes)
FORGE_LOG_LEVEL=WARN   # Apenas warnings e erros
```

## Estrutura de Logs por Módulo

| Módulo | Uso Principal | Exemplo de Log |
|--------|--------------|----------------|
| `cli` | Entrada/saída CLI | `Starting command=roteiro`, `Script saved` |
| `config` | Configuração | `Settings loaded provider=anthropic` |
| `llm.model` | Build do LLM | `Building LLM model provider=anthropic` |
| `orchestrator.graph` | Fluxo de processo | `Running research phase`, `Review completed aprovado=true` |
| `writer.research` | Pesquisa web | `Search completed num_results=3` |
| `writer.write` | Escrita do roteiro | `Write phase completed num_secoes=8` |
| `writer.review` | Revisão | `Review completed aprovado=false, notas=4` |
| `output.storage` | Gravagem de arquivo | `Script saved secoes_count=9` |

## Debugging

Para debug profundo:

```bash
# Modo debug completo
FORGE_LOG_LEVEL=DEBUG forge roteiro --tema "Filosofia"

# Verificar logs em tempo real
forge roteiro --tema "Estoicismo" 2>&1 | grep -i warning
```

## Estrutura dos Logs

Cada log inclui:
- **Timestamp** (ISO 8601)
- **Nível** (DEBUG/INFO/WARNING/ERROR)
- **Nome do módulo** (`forge.cli`, `forge.writer.write`, etc.)
- **Mensagem contextualizada** com metadados relevantes

Exemplo de log estruturado:
```
2026-07-18 10:30:45 [INFO] forge.orchestrator.graph - Review completed aprovado=true round=3
```
