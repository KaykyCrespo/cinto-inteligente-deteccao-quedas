"""Gera o Guia do Usuário e Manual de Operação em DOCX e PDF a partir de MANUAL_USUARIO_OPERACAO.md.

Requisitos: pip install pypandoc_binary python-docx pywin32 · Microsoft Word instalado (exportação do PDF).
Uso: python DOCUMENTACAO/gerar_manual.py
     python DOCUMENTACAO/gerar_manual.py --origem ROTEIRO_VIDEO.md --saida Roteiro_Video --simples
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

PASTA = os.path.dirname(os.path.abspath(__file__))
ORIGEM = os.path.join(PASTA, "MANUAL_USUARIO_OPERACAO.md")
DOCX = os.path.join(PASTA, "Manual_Usuario_Operacao.docx")
PDF = os.path.join(PASTA, "Manual_Usuario_Operacao.pdf")

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


def preparar_markdown(capa=True):
    with open(ORIGEM, encoding="utf-8") as f:
        texto = f.read()
    if capa:
        texto = re.sub(r"\A# .*\n", "", texto)                # o título vai para a capa
        texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)        # ABNT: sem negrito no corpo do texto
    texto = re.sub(r"(?m)^---\s*$\n", "", texto)
    secoes = iter(range(1000))
    texto = re.sub(r"(?m)^(## Seção )", lambda m: (QUEBRA_SECAO if capa and next(secoes) == 0 else QUEBRA)
                   + m.group(1), texto)
    texto = re.sub(r"\]\(([^)]*%20[^)]*)\)", lambda m: "](<" + m.group(1).replace("%20", " ") + ">)", texto)
    return texto


def converter_docx(texto, sumario=True):
    extras = ["--toc", "--toc-depth=2", "-M", "toc-title=Sumário"] if sumario else []
    pypandoc.convert_text(
        texto, "docx", format="markdown-implicit_figures", outputfile=DOCX,
        extra_args=extras + ["--shift-heading-level-by=-1", f"--resource-path={PASTA}", "-M", "lang=pt-BR"])


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

        for t in range(1, doc.Tables.Count + 1):
            tb = doc.Tables(t)
            tb.Borders.Enable = True
            tb.Range.Font.Size = 10
            pf = tb.Range.ParagraphFormat
            pf.Alignment, pf.FirstLineIndent, pf.LineSpacingRule = 0, 0, 0
            pf.SpaceBefore, pf.SpaceAfter = 0, 0
            tb.Rows(1).Range.Font.Bold = True
            tb.Rows(1).Shading.BackgroundPatternColor = 0xE6E6E6
            tb.Rows(1).HeadingFormat = True
            tb.AutoFitBehavior(1)
            tb.AutoFitBehavior(2)
            anterior = tb.Range.Previous(4, 1)               # parágrafo antes da tabela fica com ela
            if anterior is not None:
                anterior.ParagraphFormat.KeepWithNext = True

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
        for i in range(1, doc.Paragraphs.Count + 1):
            p = doc.Paragraphs(i)
            texto = p.Range.Text.strip()
            if re.match(r"Figura \d+ –", texto) or texto.startswith("Fonte:"):
                p.Range.Font.Size = 10
                p.Alignment, p.FirstLineIndent, p.LineSpacingRule = 1, 0, 0
                p.KeepWithNext = texto.startswith("Figura")

        if capa:
            s2 = doc.Sections(2)
            for cab in (s2.Headers(1), s2.Footers(1)):
                cab.LinkToPrevious = False
            for cab in (doc.Sections(1).Headers(1), doc.Sections(1).Footers(1)):
                cab.Range.Text = ""
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
    ap.add_argument("--origem", default="MANUAL_USUARIO_OPERACAO.md", help="Markdown dentro de DOCUMENTACAO/")
    ap.add_argument("--saida", default="Manual_Usuario_Operacao", help="nome base do DOCX/PDF")
    ap.add_argument("--simples", action="store_true", help="sem capa e sem sumário")
    a = ap.parse_args()
    ORIGEM = os.path.join(PASTA, a.origem)
    DOCX = os.path.join(PASTA, a.saida + ".docx")
    PDF = os.path.join(PASTA, a.saida + ".pdf")

    converter_docx(preparar_markdown(capa=not a.simples), sumario=not a.simples)
    if not a.simples:
        inserir_capa()
    formatar_no_word(capa=not a.simples)
    print("Gerado:", DOCX)
    print("Gerado:", PDF)
