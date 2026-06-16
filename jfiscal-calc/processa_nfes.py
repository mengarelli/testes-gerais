#!/usr/bin/env python3
"""
processa_nfes.py — Processa todos os XMLs de NF-e na pasta xmls/
e exibe o resumo dos valores totais (vNF) para notas normais e canceladas.

Gera um arquivo RESULTADO.md no diretório do script.
"""

import os
import glob
import xml.etree.ElementTree as ET

# Namespace da NF-e (padrão 4.00)
NS = {"ns": "http://www.portalfiscal.inf.br/nfe"}

DIR_RAIZ = os.path.dirname(os.path.abspath(__file__))
DIR_XMLS = os.path.join(DIR_RAIZ, "xmls")
ARQUIVO_SAIDA = os.path.join(DIR_RAIZ, "RESULTADO.md")


def extrair_chave(inf_nfe_id: str) -> str:
    """Extrai a chave de 44 dígitos a partir do atributo Id (ex: 'NFe4126...')."""
    return inf_nfe_id.replace("NFe", "")


def extrair_vnf(arquivo: str) -> tuple[str | None, float | None]:
    """
    Extrai a chave da NF-e e o vNF de um arquivo XML.
    Retorna (chave, valor_float) ou (None, None) em caso de erro.
    """
    try:
        tree = ET.parse(arquivo)
        root = tree.getroot()

        # Caminho: nfeProc/NFe/infNFe/total/ICMSTot/vNF
        inf_nfe = root.find(".//ns:infNFe", NS)
        if inf_nfe is None:
            return None, None

        chave = extrair_chave(inf_nfe.get("Id", ""))

        vnf_elem = root.find(".//ns:ICMSTot/ns:vNF", NS)
        if vnf_elem is None or vnf_elem.text is None:
            return chave, None

        valor = float(vnf_elem.text)
        return chave, valor

    except (ET.ParseError, ValueError, AttributeError) as e:
        print(f"  ❌ Erro ao processar {os.path.basename(arquivo)}: {e}")
        return None, None


def fmt_moeda(valor: float) -> str:
    """Formata valor float para padrão brasileiro R$ X.XXX,XX."""
    return f"R$ {valor:_.2f}".replace(".", ",").replace("_", ".")


def processar():
    """Função principal de processamento."""
    # Listar todos os arquivos XML
    todos_xmls = sorted(glob.glob(os.path.join(DIR_XMLS, "*.xml")))
    total_arquivos = len(todos_xmls)

    print(f"🔎 Encontrados {total_arquivos} arquivos XML na pasta xmls/")
    print("═" * 60)

    # Separar normais e canceladas
    normais = [f for f in todos_xmls if f.endswith("-nfe.xml")]
    canceladas = [f for f in todos_xmls if f.endswith("-nfe-cancelada.xml")]

    # Mapa: chave (44 dígitos) -> (arquivo_normal, valor)
    notas_processadas: dict[str, dict] = {}

    # Processa todas as notas normais
    print(f"\n📄 Processando {len(normais)} notas normais...")
    print("─" * 60)

    for arq in normais:
        chave, valor = extrair_vnf(arq)
        if chave and valor is not None:
            notas_processadas[chave] = {
                "valor": valor,
                "cancelada": False,
            }
        elif chave:
            notas_processadas[chave] = {
                "valor": None,
                "cancelada": False,
            }

    # Processa canceladas: identifica quais chaves são canceladas
    chaves_canceladas = set()
    for arq in canceladas:
        # O nome do arquivo cancelado segue o padrão:
        # 41260464026211000186550010000007231431917728-nfe-cancelada.xml
        # A mesma chave está no XML normal
        nome_base = os.path.basename(arq)
        chave = nome_base.replace("-nfe-cancelada.xml", "")
        chaves_canceladas.add(chave)

    # Marcar as canceladas
    for chave in chaves_canceladas:
        if chave in notas_processadas:
            notas_processadas[chave]["cancelada"] = True
        else:
            # Nota cancelada mas sem XML normal - tenta ler do cancelamento direto
            notas_processadas[chave] = {
                "valor": None,
                "cancelada": True,
            }

    # Cálculo dos totais
    notas_normais = {k: v for k, v in notas_processadas.items() if not v["cancelada"]}
    notas_canceladas_map = {k: v for k, v in notas_processadas.items() if v["cancelada"]}

    total_normais = sum(v["valor"] for v in notas_normais.values() if v["valor"] is not None)
    total_canceladas = sum(v["valor"] for v in notas_canceladas_map.values() if v["valor"] is not None)
    total_geral = total_normais + total_canceladas

    # ══════════════════════════════════════════════════════════
    # SAÍDA NO TERMINAL
    # ══════════════════════════════════════════════════════════

    print(f"\n{'═' * 60}")
    print(f" 📊 RESULTADO DO PROCESSAMENTO")
    print(f"{'═' * 60}")

    # Notas normais
    print(f"\n ✅ NOTAS NORMAIS ({len(notas_normais)})")
    print(f"{'─' * 60}")
    for chave, info in sorted(notas_normais.items()):
        valor_str = fmt_moeda(info["valor"]) if info["valor"] is not None else "❌ N/D"
        print(f"  ✔ {chave}: {valor_str}")

    # Notas canceladas
    print(f"\n ⚠️  NOTAS CANCELADAS ({len(notas_canceladas_map)})")
    print(f"{'─' * 60}")
    for chave, info in sorted(notas_canceladas_map.items()):
        valor_str = fmt_moeda(info["valor"]) if info["valor"] is not None else "❌ N/D"
        print(f"  ⚠ {chave}: {valor_str}")

    # Resumo
    print(f"\n{'═' * 60}")
    print(f" 📊 RESUMO FINAL")
    print(f"{'─' * 60}")
    print(f"  Total de arquivos XML encontrados:  {total_arquivos}")
    print(f"  Total de notas normais processadas: {len(notas_normais)}")
    print(f"  Total de notas canceladas:          {len(notas_canceladas_map)}")
    print(f"  Soma (notas normais):               {fmt_moeda(total_normais)}")
    print(f"  Soma (notas canceladas):            {fmt_moeda(total_canceladas)}")
    print(f"  ─────────────────────────────────────────────")
    print(f"  SOMA TOTAL GERAL:                   {fmt_moeda(total_geral)}")
    print(f"{'═' * 60}")

    # ══════════════════════════════════════════════════════════
    # GERAR ARQUIVO MARKDOWN
    # ══════════════════════════════════════════════════════════

    linhas = []
    linhas.append("# Resultado do Processamento de NF-e")
    linhas.append("")
    linhas.append("## Resumo")
    linhas.append("")
    linhas.append("| Indicador | Valor |")
    linhas.append("|-----------|-------|")
    linhas.append(f"| Total de arquivos XML encontrados | {total_arquivos} |")
    linhas.append(f"| Total de NF-es processadas | {len(notas_normais)} |")
    linhas.append(f"| Total de notas canceladas | {len(notas_canceladas_map)} |")
    linhas.append(f"| Soma (notas normais) | {fmt_moeda(total_normais)} |")
    linhas.append(f"| Soma (notas canceladas) | {fmt_moeda(total_canceladas)} |")
    linhas.append(f"| **SOMA TOTAL GERAL** | **{fmt_moeda(total_geral)}** |")
    linhas.append("")
    linhas.append("---")
    linhas.append("")
    linhas.append("## Detalhamento")
    linhas.append("")

    # Notas normais
    linhas.append("### ✅ Notas Normais")
    linhas.append("")
    linhas.append("| Chave | Valor (vNF) |")
    linhas.append("|-------|-------------|")
    for chave, info in sorted(notas_normais.items()):
        valor_str = f"**{fmt_moeda(info['valor'])}**" if info["valor"] is not None else "❌ N/D"
        linhas.append(f"| `{chave}` | {valor_str} |")
    linhas.append("")
    linhas.append(f"> **Subtotal (normais): {fmt_moeda(total_normais)}**")
    linhas.append("")

    # Notas canceladas
    linhas.append("### ⚠️ Notas Canceladas")
    linhas.append("")
    linhas.append("| Chave | Valor Original (vNF) |")
    linhas.append("|-------|----------------------|")
    for chave, info in sorted(notas_canceladas_map.items()):
        valor_str = f"**{fmt_moeda(info['valor'])}**" if info["valor"] is not None else "❌ N/D"
        linhas.append(f"| `{chave}` | {valor_str} |")
    linhas.append("")
    linhas.append(f"> **Subtotal (canceladas): {fmt_moeda(total_canceladas)}**")
    linhas.append("")

    # Total geral
    linhas.append("### 📊 Total Geral")
    linhas.append("")
    linhas.append(f"| Indicador | Valor |")
    linhas.append(f"|-----------|-------|")
    linhas.append(f"| Notas normais | {fmt_moeda(total_normais)} |")
    linhas.append(f"| Notas canceladas | {fmt_moeda(total_canceladas)} |")
    linhas.append(f"| **SOMA TOTAL GERAL** | **{fmt_moeda(total_geral)}** |")
    linhas.append("")
    linhas.append("---")
    linhas.append(f"*Gerado por `processa_nfes.py` em {__import__('datetime').datetime.now().strftime('%d/%m/%Y às %H:%M')}*")

    conteudo_md = "\n".join(linhas)

    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        f.write(conteudo_md)

    print(f"\n📝 Resultado salvo em: {ARQUIVO_SAIDA}")
    print()


if __name__ == "__main__":
    processar()
