#!/usr/bin/env python3
"""
Valida um arquivo JSON de roteiro do Conquistas Cósmicas contra o schema
e contra o Protocolo de Citações.

Uso:
    python validar_roteiro.py caminho/do/roteiro.json

Sai com código 0 se válido, 1 se houver erros (que são impressos).
Toda citação precisa de path canônico do acervo. Citações com tipo "literal"
também precisam de verificada == true E fonte não vazia. A presença do path
na pesquisa e o suporte textual exigem conferência das evidências preservadas.
"""
import json
import sys

EIXOS = {"estoicismo", "autoconhecimento", "niilismo-absurdo", "etica-digital-ia"}


def validar(dados):
    erros = []

    # meta
    meta = dados.get("meta")
    if not isinstance(meta, dict):
        erros.append("meta ausente ou não é objeto.")
    else:
        if meta.get("canal") != "Conquistas Cósmicas":
            erros.append('meta.canal deve ser "Conquistas Cósmicas".')
        if meta.get("eixo") not in EIXOS:
            erros.append(f"meta.eixo deve ser um de {sorted(EIXOS)}.")
        for campo in ("tema", "duracao_estimada_min", "gerado_em"):
            if not meta.get(campo):
                erros.append(f"meta.{campo} ausente ou vazio.")

    # titulos
    titulos = dados.get("titulos")
    if not isinstance(titulos, list) or len(titulos) != 3:
        erros.append("titulos deve ser uma lista com exatamente 3 opções.")

    # gancho
    gancho = dados.get("gancho")
    if not isinstance(gancho, dict) or not gancho.get("texto"):
        erros.append("gancho.texto ausente ou vazio.")

    # roteiro
    roteiro = dados.get("roteiro")
    total_palavras = 0
    if not isinstance(roteiro, list) or not roteiro:
        erros.append("roteiro deve ser uma lista não vazia de seções.")
    else:
        for i, sec in enumerate(roteiro):
            if not isinstance(sec, dict) or not sec.get("secao") or not sec.get("texto"):
                erros.append(f"roteiro[{i}] precisa de 'secao' e 'texto'.")
            else:
                total_palavras += len(str(sec["texto"]).split())
        if total_palavras < 1200:
            erros.append(
                f"roteiro tem ~{total_palavras} palavras; abaixo do mínimo (~1500 para 10 min)."
            )

    # citacoes — a regra central do protocolo
    citacoes = dados.get("citacoes")
    if not isinstance(citacoes, list):
        erros.append("citacoes deve ser uma lista.")
    else:
        for i, c in enumerate(citacoes):
            if not isinstance(c, dict):
                erros.append(f"citacoes[{i}] não é objeto.")
                continue
            if not c.get("autor"):
                erros.append(f"citacoes[{i}].autor ausente.")
            if not c.get("obra"):
                erros.append(f"citacoes[{i}].obra ausente (obrigatória).")
            if not isinstance(c.get("path"), str) or not c["path"].strip():
                erros.append(f"citacoes[{i}].path ausente ou vazio (caminho canônico do acervo obrigatório).")
            tipo = c.get("tipo")
            if tipo not in ("literal", "parafrase"):
                erros.append(f'citacoes[{i}].tipo deve ser "literal" ou "parafrase".')
            if tipo == "literal":
                if c.get("verificada") is not True:
                    erros.append(
                        f"citacoes[{i}] é literal mas verificada != true. "
                        "Verifique com busca ou rebaixe para paráfrase."
                    )
                if not c.get("fonte"):
                    erros.append(
                        f"citacoes[{i}] é literal mas fonte está vazia. "
                        "Toda citação literal precisa de fonte rastreável do acervo."
                    )

    # cenas
    cenas = dados.get("cenas")
    if not isinstance(cenas, list) or len(cenas) < 6:
        erros.append("cenas deve ter pelo menos 6 sugestões.")

    return erros


def main():
    if len(sys.argv) != 2:
        print("Uso: python validar_roteiro.py caminho/do/roteiro.json")
        sys.exit(1)

    caminho = sys.argv[1]
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERRO: JSON inválido — {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"ERRO: arquivo não encontrado — {caminho}")
        sys.exit(1)

    erros = validar(dados)
    if erros:
        print(f"REPROVADO — {len(erros)} problema(s):")
        for e in erros:
            print(f"  - {e}")
        sys.exit(1)

    print("APROVADO — o roteiro passou em todas as verificações do schema e do protocolo.")
    sys.exit(0)


if __name__ == "__main__":
    main()
