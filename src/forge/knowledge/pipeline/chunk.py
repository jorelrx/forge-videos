"""Documento -> chunks com overlap.

Quando o documento tem seções (livro estruturado), corta dentro de cada seção e
carrega o nome do capítulo para a proveniência do chunk — é o que dá 'capítulo X'
na citação. Sem seções (web, ou livro sem estrutura detectada), corta o texto
inteiro.
"""
from forge.knowledge.domain.models import Chunk, Documento, Proveniencia

def _dividir(texto: str, size: int, overlap: int) -> list[str]:
    texto = texto.strip()
    if not texto:
        return []
    if len(texto) <= size:
        return [texto]

    pedacos: list[str] = []
    i = 0
    while i < len(texto):
        fim = min(i + size, len(texto))
        # Estende para trás até um espaço para não cortar palavra ao meio.
        if fim < len(texto):
            espaco = texto.rfind(" ", i, fim)
            if espaco > i:
                fim = espaco
        pedaco = texto[i:fim].strip()
        if pedaco:
            pedacos.append(pedaco)
        if fim >= len(texto):
            break
        # Recua `overlap` para a próxima janela; max(..., i+1) garante avanço.
        i = max(fim - overlap, i + 1)
    return pedacos

def _proveniencia_secao(base: Proveniencia, secao: str | None) -> Proveniencia:
    if secao is None or base.tipo != "livro":
        return base
    return base.model_copy(update={"capitulo": secao})

def chunk_documento(doc: Documento, *, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    unidades: list[tuple[str | None, str]]
    if doc.secoes:
        unidades = [(s.nome, s.texto) for s in doc.secoes]
    else:
        unidades = [(None, doc.texto)]

    chunks: list[Chunk] = []
    ordem = 0
    for secao, texto in unidades:
        for pedaco in _dividir(texto, chunk_size, chunk_overlap):
            chunks.append(
                Chunk(
                    documento_id=doc.id,
                    ordem=ordem,
                    texto=pedaco,
                    proveniencia=_proveniencia_secao(doc.proveniencia, secao),
                    secao=secao,
                )
            )
            ordem += 1
    return chunks
