"""Gera o manual ou o roteiro de vídeo em DOCX e PDF a partir de Markdown.

Requisitos: pip install pypandoc_binary python-docx pywin32 · Microsoft Word instalado (exportação do PDF).
Uso: python docs/gerar_documentos.py
    python docs/gerar_documentos.py --origem "VIDEO TECNICO/ROTEIRO_VIDEO.md" --saida "VIDEO TECNICO/Roteiro_Video" --simples
"""
import argparse
import os
import re

import pypandoc
import win32com.client
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph

PASTA_DOCUMENTACAO = os.path.dirname(os.path.abspath(__file__))
ORIGEM = os.path.join(PASTA_DOCUMENTACAO, "MANUAL", "MANUAL_USUARIO_OPERACAO.md")
DOCX = os.path.join(PASTA_DOCUMENTACAO, "MANUAL", "Manual_Usuario_Operacao.docx")
PDF = os.path.join(PASTA_DOCUMENTACAO, "MANUAL", "Manual_Usuario_Operacao.pdf")

QUEBRA = '\n```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n\n'
# quebra de seção antes da Seção 1: capa, folha de rosto e sumário ficam sem número de página (ABNT)
QUEBRA_SECAO = ('\n```{=openxml}\n<w:p><w:pPr><w:sectPr><w:type w:val="nextPage"/></w:sectPr></w:pPr></w:p>\n'
                '```\n\n')
TITULO = ("CINTO INTELIGENTE COM IoT E INTELIGÊNCIA ARTIFICIAL PARA MONITORAMENTO DE ATIVIDADES, "
          "SINAIS VITAIS E LOCALIZAÇÃO INDOOR")
SUBTITULO = "Sistema de Detecção de Possíveis Quedas"
INTEGRANTES = [("ALUISIO PEREIRA ALVES", "N135891"), ("ENZO ORLANDI GOMES", "G788EJ5"),
               ("ERICK DE BRITO CARVALHO", "G78HED3"), ("KAYKY CRESPO DOS SANTOS", "G839226")]
NATUREZA = ("Guia do Usuário e Manual de Operação do conjunto prototipado, apresentado ao Curso de Ciência "
            "da Computação da Universidade Paulista – UNIP como entregável do Trabalho de Conclusão de Curso, "
            "na vertente SmartCity – Cidades Inteligentes e Infraestrutura Urbana.")


def adicionar_fontes_tabelas(texto):
    linhas = texto.splitlines()
    resultado = []

    def linha_tabela(linha):
        linha = linha.strip()
        return linha.startswith("|") and linha.endswith("|")

    def linha_separadora(linha):
        colunas = linha.strip().strip("|").split("|")
        return len(colunas) >= 2 and all(re.fullmatch(r"\s*:?-{3,}:?\s*", coluna) for coluna in colunas)

    indice = 0
    while indice < len(linhas):
        if (indice + 1 < len(linhas) and linha_tabela(linhas[indice])
                and linha_separadora(linhas[indice + 1])):
            resultado.extend(linhas[indice:indice + 2])
            indice += 2
            while indice < len(linhas) and linha_tabela(linhas[indice]):
                resultado.append(linhas[indice])
                indice += 1
            proxima_linha = indice
            while proxima_linha < len(linhas) and not linhas[proxima_linha].strip():
                proxima_linha += 1
            if not (proxima_linha < len(linhas) and linhas[proxima_linha].strip().startswith("Fonte:")):
                resultado.extend(["", "Fonte: Elaborado pelos autores (2026).", ""])
            continue
        resultado.append(linhas[indice])
        indice += 1
    return "\n".join(resultado)


def preparar_markdown(capa=True):
    with open(ORIGEM, encoding="utf-8") as f:
        texto = f.read()
    if capa:
        texto = adicionar_fontes_tabelas(texto)
        texto = re.sub(r"\A# .*\n", "", texto)                # o título vai para a capa
        corpo, separador, referencias = texto.partition("## Referências")
        texto = re.sub(r"\*\*(.+?)\*\*", r"\1", corpo) + separador + referencias
    texto = re.sub(r"(?m)^---\s*$\n", "", texto)
    secoes = iter(range(1000))
    texto = re.sub(r"(?m)^(## Seção )", lambda m: (QUEBRA_SECAO if capa and next(secoes) == 0 else QUEBRA)
                   + m.group(1), texto)
    texto = re.sub(r"\]\(([^)]*%20[^)]*)\)", lambda m: "](<" + m.group(1).replace("%20", " ") + ">)", texto)
    texto = re.sub(r"(?m)^(### 3\.2 )", lambda m: QUEBRA + m.group(1), texto)
    texto = re.sub(r"(?m)^(### 2\.3 )", lambda m: QUEBRA + m.group(1), texto)
    texto = re.sub(r"(?m)^(## Referências)", lambda m: QUEBRA + m.group(1), texto)
    if capa:
        texto = re.sub(r"(?m)^(\*\*Figura 11 –)", lambda m: QUEBRA + m.group(1), texto)
    return texto


def converter_docx(texto, sumario=True):
    extras = ["--toc", "--toc-depth=3", "-M", "toc-title=Sumário"] if sumario else []
    pypandoc.convert_text(
        texto, "docx", format="markdown-implicit_figures", outputfile=DOCX,
        extra_args=extras + ["--shift-heading-level-by=-1",
                             f"--resource-path={os.pathsep.join((PASTA_DOCUMENTACAO, os.path.join(PASTA_DOCUMENTACAO, 'MANUAL')))}",
                             "-M", "lang=pt-BR"])


def inserir_capa():
    """Capa e folha de rosto no mesmo modelo da parte escrita do TCC."""
    doc = Document(DOCX)
    corpo = doc.element.body
    novos = []

    def par(texto="", negrito=False, antes=0, tam=12, recuo=None, justificar=False, simples=False):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY if justificar else WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.space_before, pf.space_after, pf.first_line_indent = Pt(antes), Pt(0), Cm(0)
        pf.line_spacing = 1.0 if simples else 1.5
        if recuo:
            pf.left_indent = Cm(recuo)
        if texto:
            r = p.add_run(texto)
            r.font.name, r.font.size, r.bold = "Arial", Pt(tam), negrito
        novos.append(p)
        return p

    def rodape_local():
        par("SÃO PAULO", True, antes=185)
        par("2026", True).add_run().add_break(WD_BREAK.PAGE)

    # capa
    par("UNIVERSIDADE PAULISTA – UNIP", True)
    par("CURSO DE CIÊNCIA DA COMPUTAÇÃO", True)
    for i, (nome, ra) in enumerate(INTEGRANTES):
        par(f"{nome} {ra}", antes=120 if i == 0 else 0)
    par(TITULO, True, antes=130)
    par(SUBTITULO, antes=6)
    par("Guia do Usuário e Manual de Operação", antes=6)
    rodape_local()

    # folha de rosto
    for nome, ra in INTEGRANTES:
        par(f"{nome} – RA {ra}")
    par(TITULO, True, antes=130)
    par(SUBTITULO, antes=6)
    par(NATUREZA, antes=60, tam=10, recuo=8, justificar=True, simples=True)
    par("Orientador: Prof. Marco Gomes", antes=12, tam=10, recuo=8, justificar=True, simples=True)
    rodape_local()

    for i, p in enumerate(novos):
        corpo.insert(i, p._p)

    # título do sumário fica dentro do controle de conteúdo gerado pelo pandoc
    sdt = corpo.find(qn("w:sdt"))
    if sdt is not None:
        titulo = Paragraph(next(sdt.iter(qn("w:p"))), doc._body)
        titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        titulo.paragraph_format.space_after = Pt(18)
        for r in titulo.runs:
            r.font.name, r.font.size, r.bold, r.font.all_caps = "Arial", Pt(12), True, True
            r.font.color.rgb = RGBColor(0, 0, 0)
    doc.save(DOCX)


def formatar_no_word(capa=True):
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(DOCX)
        cm = 28.3465
        for s in range(1, doc.Sections.Count + 1):
            ps = doc.Sections(s).PageSetup
            ps.PaperSize = 7                                  # A4
            ps.TopMargin, ps.LeftMargin, ps.BottomMargin, ps.RightMargin = 3 * cm, 3 * cm, 2 * cm, 2 * cm
        largura_util = 16 * cm

        def estilo(nome, fonte="Arial", tam=None, negrito=None, alinhar=None, antes=None, depois=None,
                   recuo=None, entrelinha=None, maiusculas=None):
            try:
                st = doc.Styles(nome)
            except Exception:
                return
            st.Font.Name = fonte
            st.Font.Color = 0                                 # preto
            if tam:
                st.Font.Size = tam
            if negrito is not None:
                st.Font.Bold = negrito
            if maiusculas is not None:
                st.Font.AllCaps = maiusculas
            pf = st.ParagraphFormat
            if alinhar is not None:
                pf.Alignment = alinhar
            if antes is not None:
                pf.SpaceBefore = antes
            if depois is not None:
                pf.SpaceAfter = depois
            if recuo is not None:
                pf.FirstLineIndent = recuo
            if entrelinha is not None:
                pf.LineSpacingRule = entrelinha               # 0 = simples, 1 = 1,5 linha

        # ABNT (NBR 14724), no mesmo padrão da parte escrita: Arial 12, 1,5 entre linhas, recuo de 1,25 cm
        estilo(-1, tam=12, entrelinha=1, antes=0, depois=0)                       # Normal
        for nome in (-67, "First Paragraph"):                                     # Corpo de texto
            estilo(nome, tam=12, alinhar=3, entrelinha=1, antes=0, depois=6, recuo=1.25 * cm)
        estilo("Compact", tam=12, alinhar=3, entrelinha=1, antes=0, depois=3, recuo=0)
        estilo("Block Text", tam=11, alinhar=3, entrelinha=0, antes=6, depois=6, recuo=0)
        estilo(-2, tam=12, negrito=True, maiusculas=True, alinhar=0, antes=0, depois=18, recuo=0)
        for nivel in (-3, -4, -5, -6):
            estilo(nivel, tam=12, negrito=True, alinhar=0, antes=18, depois=12, recuo=0)
        estilo("Source Code", fonte="Consolas", tam=9, entrelinha=0, recuo=0)
        estilo("TOC Heading", tam=12, negrito=True, maiusculas=True, alinhar=1, antes=0, depois=18, recuo=0)
        for nivel in (-20, -21, -22):                                             # Sumário 1 a 3
            estilo(nivel, tam=12, entrelinha=0, antes=0, depois=6, recuo=0)

        for table_index in range(1, doc.Tables.Count + 1):
            tb = doc.Tables(table_index)
            tb.Borders.Enable = True
            tb.Range.Font.Size = 10
            pf = tb.Range.ParagraphFormat
            pf.Alignment, pf.FirstLineIndent, pf.LineSpacingRule = 0, 0, 0
            pf.SpaceBefore, pf.SpaceAfter = 0, 0
            tb.AutoFitBehavior(1)
            tb.AutoFitBehavior(2)

            column_count = tb.Columns.Count
            longest_cells = []
            for column_index in range(1, column_count + 1):
                longest_cell = 0
                for row_index in range(1, tb.Rows.Count + 1):
                    cell_text = tb.Cell(row_index, column_index).Range.Text.replace("\r", " ").replace("\x07", " ").strip()
                    longest_cell = max(longest_cell, len(cell_text))
                longest_cells.append(longest_cell)

            minimum_widths_cm = [1.0 if length <= 5 else 1.4 if length <= 12 else 1.8 if length <= 24 else 2.1
                                 for length in longest_cells]
            remaining_width_cm = largura_util / cm - sum(minimum_widths_cm)
            column_weights = [max(1, min(length, 100)) ** 0.65 for length in longest_cells]
            total_weight = sum(column_weights)
            column_widths_cm = [minimum + remaining_width_cm * weight / total_weight
                                for minimum, weight in zip(minimum_widths_cm, column_weights)]

            tb.AllowAutoFit = False
            altura_estimada_pt = 0
            for column_index, width_cm in enumerate(column_widths_cm, start=1):
                tb.Columns(column_index).Width = width_cm * cm

            for row_index in range(1, tb.Rows.Count + 1):
                linhas_estimadas = 1
                for column_index, width_cm in enumerate(column_widths_cm, start=1):
                    cell_text = tb.Cell(row_index, column_index).Range.Text.replace("\r", " ").replace("\x07", " ").strip()
                    caracteres_por_linha = max(6, int(width_cm * 5.2))
                    linhas_celula = max(1, (len(cell_text) + caracteres_por_linha - 1) // caracteres_por_linha)
                    linhas_estimadas = max(linhas_estimadas, linhas_celula)
                altura_estimada_pt += linhas_estimadas * 12 + 5
                row = tb.Rows(row_index)
                row.AllowBreakAcrossPages = False
                row.Range.ParagraphFormat.KeepWithNext = altura_estimada_pt <= 620

            tb.Rows(1).Range.Font.Bold = True
            tb.Rows(1).Shading.BackgroundPatternColor = 0xE6E6E6
            tb.Rows(1).HeadingFormat = True
            anterior = tb.Range.Previous(4, 1)               # parágrafo antes da tabela fica com ela
            if anterior is not None:
                anterior.ParagraphFormat.KeepWithNext = True
                if anterior.Text.strip().startswith("Tabela "):
                    tb.Borders.Enable = False
                    tb.Borders(-1).LineStyle = 1
                    tb.Borders(-3).LineStyle = 1
                    tb.Rows(1).Borders(-3).LineStyle = 1

        for i in range(1, doc.ListParagraphs.Count + 1):
            doc.ListParagraphs(i).FirstLineIndent = 0

        for i in range(1, doc.InlineShapes.Count + 1):
            sh = doc.InlineShapes(i)
            sh.LockAspectRatio = True
            if sh.Width > largura_util:
                sh.Width = largura_util
            if sh.Height > 20 * cm:
                sh.Height = 20 * cm
            sh.Range.ParagraphFormat.Alignment = 1

        # legenda acima e fonte abaixo da figura, em tamanho menor (ABNT)
        em_referencias = False
        for i in range(1, doc.Paragraphs.Count + 1):
            p = doc.Paragraphs(i)
            texto = p.Range.Text.strip()
            if texto in {
                "Cinto (1 unidade)",
                "Antena (por unidade; montar 3: Anchor 1, Anchor 2, Anchor 3)",
                "Infraestrutura",
            }:
                p.Alignment = 1
                p.Range.Font.Bold = True
            legenda = bool(re.match(r"(?:Figura|Tabela|Quadro) \d+ –", texto))
            fonte = texto.startswith(("Fonte:", "Fonte das figuras:"))
            if legenda or fonte:
                p.Range.Font.Size = 10
                p.Alignment, p.FirstLineIndent, p.LineSpacingRule = 1, 0, 0
                p.KeepWithNext = legenda
            if p.Range.InlineShapes.Count:
                p.KeepWithNext = True
            if texto.casefold() == "referências":
                em_referencias = True
                p.Alignment = 1
            elif em_referencias and texto:
                p.Range.Font.Size = 12
                p.Alignment, p.FirstLineIndent, p.LineSpacingRule = 0, 0, 0
                p.SpaceAfter = 12
                p.KeepWithNext = False

        if capa:
            s2 = doc.Sections(2)
            for cab in (s2.Headers(1), s2.Footers(1)):
                cab.LinkToPrevious = False
            for cab in (doc.Sections(1).Headers(1), doc.Sections(1).Footers(1)):
                cab.Range.Text = ""
            doc.Sections(1).Headers(1).PageNumbers.RestartNumberingAtSection = True
            doc.Sections(1).Headers(1).PageNumbers.StartingNumber = 0
            s2.Headers(1).PageNumbers.RestartNumberingAtSection = False
            s2.Headers(1).PageNumbers.Add(2, True)            # canto superior direito, a partir do texto
        else:
            doc.Sections(1).Footers(1).PageNumbers.Add(2, True)
        for i in range(1, doc.TablesOfContents.Count + 1):
            doc.TablesOfContents(i).Update()
        doc.Fields.Update()
        doc.Save()
        doc.ExportAsFixedFormat(PDF, 17)                      # wdExportFormatPDF
        doc.Close(False)
    finally:
        word.Quit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--origem", default="MANUAL/MANUAL_USUARIO_OPERACAO.md", help="Markdown relativo a docs/")
    ap.add_argument("--saida", default="MANUAL/Manual_Usuario_Operacao", help="caminho base do DOCX/PDF relativo a docs/")
    ap.add_argument("--simples", action="store_true", help="sem capa e sem sumário")
    a = ap.parse_args()
    ORIGEM = os.path.join(PASTA_DOCUMENTACAO, a.origem)
    DOCX = os.path.join(PASTA_DOCUMENTACAO, a.saida + ".docx")
    PDF = os.path.join(PASTA_DOCUMENTACAO, a.saida + ".pdf")

    converter_docx(preparar_markdown(capa=not a.simples), sumario=not a.simples)
    if not a.simples:
        inserir_capa()
    formatar_no_word(capa=not a.simples)
    print("Gerado:", DOCX)
    print("Gerado:", PDF)
