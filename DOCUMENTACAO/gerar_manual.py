"""Gera o Guia do Usuário e Manual de Operação em DOCX e PDF a partir de MANUAL_USUARIO_OPERACAO.md.

Requisitos: pip install pypandoc_binary python-docx pywin32 · Microsoft Word instalado (exportação do PDF).
Uso: python DOCUMENTACAO/gerar_manual.py
"""
import os
import re

import pypandoc
import win32com.client
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Cm, Pt, RGBColor

PASTA = os.path.dirname(os.path.abspath(__file__))
ORIGEM = os.path.join(PASTA, "MANUAL_USUARIO_OPERACAO.md")
DOCX = os.path.join(PASTA, "Manual_Usuario_Operacao_OQPNB.docx")
PDF = os.path.join(PASTA, "Manual_Usuario_Operacao_OQPNB.pdf")
LOGO = os.path.join(PASTA, "APOIO", "IMAGENS", "LOGO UNIP.png")

QUEBRA = '\n```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```\n\n'
EQUIPE = [
    "ALUISIO PEREIRA ALVES – RA N135891",
    "ENZO ORLANDI GOMES – RA G788EJ5",
    "ERICK DE BRITO CARVALHO – RA G78HED3",
    "KAYKY CRESPO DOS SANTOS – RA G839226",
]
AZUL_ESCURO = RGBColor(0x1F, 0x3A, 0x5F)


def preparar_markdown():
    with open(ORIGEM, encoding="utf-8") as f:
        texto = f.read()
    texto = re.sub(r"\A# .*\n", "", texto)                    # o título vai para a capa
    texto = re.sub(r"(?m)^---\s*$\n", "", texto)
    texto = re.sub(r"(?m)^(## Seção )", QUEBRA.replace("\\", "\\\\") + r"\1", texto)
    texto = re.sub(r"\]\(([^)]*%20[^)]*)\)", lambda m: "](<" + m.group(1).replace("%20", " ") + ">)", texto)
    return texto


def converter_docx(texto):
    pypandoc.convert_text(
        texto, "docx", format="markdown-implicit_figures", outputfile=DOCX,
        extra_args=["--toc", "--toc-depth=2", "--shift-heading-level-by=-1", f"--resource-path={PASTA}",
                    "-M", "toc-title=Sumário", "-M", "lang=pt-BR"])


def inserir_capa():
    doc = Document(DOCX)
    corpo = doc.element.body
    novos = []

    def par(texto="", tam=12, negrito=False, cor=None, espaco=0):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(espaco)
        if texto:
            r = p.add_run(texto)
            r.font.name, r.font.size, r.bold = "Arial", Pt(tam), negrito
            if cor:
                r.font.color.rgb = cor
        novos.append(p)
        return p

    if os.path.exists(LOGO):
        par().add_run().add_picture(LOGO, width=Cm(4))
    par("UNIVERSIDADE PAULISTA – UNIP", 14, True)
    par("CURSO DE CIÊNCIA DA COMPUTAÇÃO", 12, True, espaco=36)
    for nome in EQUIPE:
        par(nome, 12)
    par(espaco=60)
    par("GUIA DO USUÁRIO E MANUAL DE OPERAÇÃO", 16, True, AZUL_ESCURO, 12)
    par("CINTO INTELIGENTE COM IoT E INTELIGÊNCIA ARTIFICIAL PARA MONITORAMENTO DE ATIVIDADES, "
        "SINAIS VITAIS E LOCALIZAÇÃO INDOOR", 13, True, espaco=6)
    par("Sistema de Detecção de Possíveis Quedas (OQPNB)", 12, espaco=24)
    par("Vertente: SmartCity – Cidades Inteligentes e Infraestrutura Urbana", 12, True, AZUL_ESCURO, 6)
    par("Orientador: Prof. Marco Gomes", 12, espaco=90)
    par("SÃO PAULO", 12, True)
    fim = par("2026", 12, True)
    fim.add_run().add_break(WD_BREAK.PAGE)

    for i, p in enumerate(novos):
        corpo.insert(i, p._p)
    doc.save(DOCX)


def formatar_no_word():
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

        def estilo(nome, fonte="Arial", tam=None, negrito=None, cor=None, alinhar=None, depois=None):
            try:
                st = doc.Styles(nome)
            except Exception:
                return
            st.Font.Name = fonte
            if tam:
                st.Font.Size = tam
            if negrito is not None:
                st.Font.Bold = negrito
            if cor is not None:
                st.Font.Color = cor
            if alinhar is not None:
                st.ParagraphFormat.Alignment = alinhar
            if depois is not None:
                st.ParagraphFormat.SpaceAfter = depois

        azul = 0x5F3A1F                                       # BGR de #1F3A5F
        estilo(-1, tam=11)                                    # Normal
        estilo(-67, tam=11, alinhar=3, depois=6)              # Corpo de texto (justificado)
        estilo("First Paragraph", tam=11, alinhar=3, depois=6)
        estilo("Compact", tam=9)
        estilo(-2, tam=16, negrito=True, cor=azul)            # Título 1 (Seções)
        estilo(-3, tam=13, negrito=True, cor=azul)
        estilo(-4, tam=11.5, negrito=True, cor=azul)
        estilo(-5, tam=11, negrito=True, cor=azul)
        estilo("Source Code", fonte="Consolas", tam=8.5)

        for t in range(1, doc.Tables.Count + 1):
            tb = doc.Tables(t)
            tb.Borders.Enable = True
            tb.Range.Font.Size = 9
            tb.Range.ParagraphFormat.Alignment = 0
            tb.Rows(1).Range.Font.Bold = True
            tb.Rows(1).Shading.BackgroundPatternColor = 0xFBF0E8   # BGR de #E8F0FB
            tb.Rows(1).HeadingFormat = True
            tb.AutoFitBehavior(1)
            tb.AutoFitBehavior(2)

        for i in range(1, doc.InlineShapes.Count + 1):
            sh = doc.InlineShapes(i)
            sh.LockAspectRatio = True
            if sh.Width > largura_util:
                sh.Width = largura_util
            if sh.Height > 20 * cm:
                sh.Height = 20 * cm
            sh.Range.ParagraphFormat.Alignment = 1

        # legenda "Figura N" e rótulos em negrito antes de tabelas ficam na mesma página do conteúdo
        for i in range(1, doc.Paragraphs.Count + 1):
            p = doc.Paragraphs(i)
            texto = p.Range.Text.strip()
            if texto.startswith("Figura ") or (texto.endswith(":") and p.Range.Font.Bold == -1):
                p.KeepWithNext = True

        rodape = doc.Sections(1).Footers(1)
        rodape.PageNumbers.Add(2, False)                      # à direita, sem número na capa
        for i in range(1, doc.TablesOfContents.Count + 1):
            doc.TablesOfContents(i).Update()
        doc.Fields.Update()
        doc.Save()
        doc.ExportAsFixedFormat(PDF, 17)                      # wdExportFormatPDF
        doc.Close(False)
    finally:
        word.Quit()


if __name__ == "__main__":
    converter_docx(preparar_markdown())
    inserir_capa()
    formatar_no_word()
    print("Gerado:", DOCX)
    print("Gerado:", PDF)
