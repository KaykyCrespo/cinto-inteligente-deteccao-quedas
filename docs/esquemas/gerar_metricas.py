"""Gera a matriz de confusão e o painel de métricas do modelo a partir de modelos/resultado_treino_mvp_8g.txt.

Uso: python docs/esquemas/gerar_metricas.py
"""
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "..", "..", "modelos", "resultado_treino_mvp_8g.txt")

AZUL = "#2f6fd6"
TEXTO = "#222222"
VERDE = "#28734a"
VERMELHO = "#a33b35"
FONTE = "Fonte das figuras: elaborado pelos autores (2026)."
ORIGEM = "Dados: relatório de treinamento no SisFall (resultado_treino_mvp_8g.txt)."

plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"],
                     "font.size": 11, "text.color": TEXTO, "axes.labelcolor": TEXTO,
                     "xtick.color": TEXTO, "ytick.color": TEXTO, "svg.fonttype": "none"})


def ler_relatorio():
    with open(RELATORIO, encoding="utf-8") as f:
        txt = f.read()
    configuracao = re.search(r"Validação cruzada por voluntário \((\d+) folds\), limiar ([\d.]+):", txt)
    positivos = re.search(r"Sensibilidade [\d.]+\s+\((\d+)/(\d+) quedas", txt)
    negativos = re.search(r"\((\d+) alarmes falsos em (\d+) atividades\)", txt)
    if not configuracao or not positivos or not negativos or "Importância das features:" not in txt:
        raise ValueError("Relatório incompleto: faltam configuração, contagens ou importâncias.")
    folds = int(configuracao.group(1))
    limiar = float(configuracao.group(2))
    vp, quedas = map(int, positivos.groups())
    fp, atividades = map(int, negativos.groups())
    limiares = [(float(a), float(b), float(c)) for a, b, c in
                re.findall(r"limiar ([\d.]+): sensibilidade ([\d.]+)\s+especificidade ([\d.]+)", txt)]
    imp = [(n, float(v)) for n, v in re.findall(r"(\w+)=([\d.]+)", txt.split("Importância das features:")[1])]
    if (quedas <= 0 or atividades <= 0 or not 0 <= vp <= quedas or not 0 <= fp <= atividades
            or folds < 2 or not 0 <= limiar <= 1 or not limiares or not imp
            or any(not 0 <= valor <= 1 for linha in limiares for valor in linha)
            or any(not 0 <= valor <= 1 for _, valor in imp)):
        raise ValueError("Relatório com contagens, configuração ou valores inválidos.")
    referencia = next((linha for linha in limiares if abs(linha[0] - limiar) < 1e-9), None)
    if referencia and (abs(referencia[1] - vp / quedas) > 0.00051
                       or abs(referencia[2] - (atividades - fp) / atividades) > 0.00051):
        raise ValueError("Os valores do limiar de referência não conferem com as contagens.")
    return vp, quedas - vp, fp, atividades - fp, limiares, imp, folds, limiar


def pct(v):
    return f"{v * 100:.1f}%".replace(".", ",")


def contexto(folds, limiar, total):
    valor = f"{limiar:.2f}".replace(".", ",")
    quantidade = f"{total:,}".replace(",", ".")
    return f"SisFall · GroupKFold por voluntário · {folds} folds · limiar {valor} · {quantidade} ensaios"


def matriz(vp, fn, fp, vn, folds, limiar):
    fig = plt.figure(figsize=(9, 8.8))
    ax = fig.add_axes([0.27, 0.30, 0.66, 0.59])
    fig.suptitle("Matriz de confusão do detector de quedas", fontsize=16, y=0.98)
    fig.text(0.5, 0.94, contexto(folds, limiar, vp + fn + fp + vn), ha="center", fontsize=11)
    celulas = [[(vp, "VP", True), (fn, "FN", False)], [(fp, "FP", False), (vn, "VN", True)]]
    totais = [vp + fn, fp + vn]
    for i, linha in enumerate(celulas):
        for j, (n, sigla, acerto) in enumerate(linha):
            frac = n / totais[i]
            cor = AZUL if acerto else VERMELHO
            ax.add_patch(plt.Rectangle((j, 1 - i), 1, 1, fc=cor, alpha=0.12 + 0.75 * frac, ec="white", lw=3))
            escuro = frac > 0.5
            ax.text(j + 0.5, 1 - i + 0.62, f"{n:,}".replace(",", "."), ha="center", va="center", fontsize=26,
                    fontweight="bold", color="white" if escuro else TEXTO)
            ax.text(j + 0.5, 1 - i + 0.36, f"{sigla} · {pct(frac)}", ha="center", va="center", fontsize=13,
                    color="white" if escuro else TEXTO)
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.set_xticks([0.5, 1.5], ["Queda", "Atividade sem queda"], fontsize=12, color=TEXTO)
    ax.set_yticks([1.5, 0.5], [f"Queda\n({vp + fn:,} ensaios)".replace(",", "."),
                               f"Atividade sem queda\n({fp + vn:,} ensaios)".replace(",", ".")],
                  fontsize=11, color=TEXTO)
    ax.set_xlabel("Classe prevista", fontsize=12, labelpad=12)
    ax.set_ylabel("Classe real", fontsize=12, labelpad=14)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_aspect("equal")
    notas = [FONTE, ORIGEM,
             "Nota: contagens por ensaio; percentuais calculados sobre o total de cada classe real.",
             "VP: verdadeiro positivo; FN: falso negativo; FP: falso positivo; VN: verdadeiro negativo.",
             "Ensaio positivo: ao menos uma janela com probabilidade maior ou igual ao limiar.",
             "Este critério não mede atraso de detecção nem taxa de falsos alarmes por hora."]
    for indice, texto in enumerate(notas):
        fig.text(0.06, 0.19 - indice * 0.028, texto, ha="left", fontsize=10)
    salvar(fig, "matriz_confusao")


def painel(vp, fn, fp, vn, limiares, imp, folds, limiar):
    rec = vp / (vp + fn)
    esp = vn / (vn + fp)
    prec = vp / (vp + fp)
    f1 = 2 * prec * rec / (prec + rec)
    acc = (vp + vn) / (vp + fn + fp + vn)

    fig = plt.figure(figsize=(14, 9))
    fig.suptitle("Avaliação do detector de quedas e importância dos atributos", fontsize=17, y=0.98)
    fig.text(0.5, 0.94, f"Random Forest · {len(imp)} atributos · "
             + contexto(folds, limiar, vp + fn + fp + vn), ha="center", fontsize=11)

    metricas = [("Sensibilidade", rec, "VP / (VP + FN)"), ("Precisão", prec, "VP / (VP + FP)"),
               ("F1-score", f1, "2VP / (2VP + FP + FN)"), ("Especificidade", esp, "VN / (VN + FP)"),
               ("Acurácia", acc, "(VP + VN) / total")]
    topo = fig.add_axes([0.04, 0.75, 0.92, 0.13])
    topo.axis("off")
    topo.set_xlim(0, 5)
    topo.set_ylim(0, 1)
    for indice, (nome, valor, formula) in enumerate(metricas):
        centro = indice + 0.5
        topo.text(centro, 0.88, nome, ha="center", fontsize=12)
        topo.text(centro, 0.42, pct(valor), ha="center", fontsize=27, fontweight="bold")
        topo.text(centro, 0.08, formula, ha="center", fontsize=10)
    topo.axhline(0, color="#555555", lw=0.8)

    ax1 = fig.add_axes([0.07, 0.28, 0.35, 0.36])
    lim = [l[0] for l in limiares]
    ax1.plot(lim, [l[1] * 100 for l in limiares], "o-", color=AZUL, lw=2, label="Sensibilidade")
    ax1.plot(lim, [l[2] * 100 for l in limiares], "s-", color=VERDE, lw=2, label="Especificidade")
    valor_limiar = f"{limiar:.2f}".replace(".", ",")
    ax1.axvline(limiar, color="#555555", ls="--", lw=1.2,
                label=f"Limiar de referência: {valor_limiar}")
    ax1.set_ylim(0, 100)
    ax1.set_xticks(sorted(set(lim + [limiar])))
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda valor, _: f"{valor:.2f}".replace(".", ",")))
    ax1.set_xlabel("Limiar da probabilidade de queda", fontsize=11, labelpad=10)
    ax1.set_ylabel("Desempenho por ensaio (%)", fontsize=11)
    ax1.set_title("(a) Sensibilidade e especificidade por limiar", fontsize=12, pad=14)
    ax1.legend(loc="lower left", fontsize=10, frameon=False)
    ax1.set_axisbelow(True)
    ax1.grid(axis="y", alpha=0.3)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    ax2 = fig.add_axes([0.69, 0.28, 0.27, 0.36])
    nomes = {"tilt": "Variação de inclinação\n(tilt)",
             "gstd": "Desvio padrão da magnitude\nda velocidade angular (gstd)",
             "amax": "Magnitude máxima\nda aceleração (amax)",
             "gmax": "Magnitude máxima\nda velocidade angular (gmax)",
             "astd": "Desvio padrão da magnitude\nda aceleração (astd)",
             "jerk": "Variação máxima de |a|\npor segundo (jerk)",
             "post_std": "Desvio padrão de |a|\nno fim da janela (post_std)",
             "amin": "Magnitude mínima\nda aceleração (amin)"}
    imp = sorted(imp, key=lambda t: t[1])
    ax2.barh([nomes.get(n, n) for n, _ in imp], [v for _, v in imp], color=AZUL, alpha=0.85)
    for y, (_, v) in enumerate(imp):
        ax2.text(v + 0.005, y, f"{v:.2f}".replace(".", ","), va="center", fontsize=10, color=TEXTO)
    ax2.set_xlim(0, max(v for _, v in imp) * 1.2)
    ax2.set_title("(b) Importância no modelo final", fontsize=12, pad=14)
    ax2.set_xlabel("Redução média de impureza (adimensional)", fontsize=11, labelpad=10)
    ax2.xaxis.set_major_formatter(FuncFormatter(lambda valor, _: f"{valor:.2f}".replace(".", ",")))
    ax2.tick_params(labelsize=10)
    ax2.set_axisbelow(True)
    ax2.grid(axis="x", alpha=0.3)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)

    notas = [FONTE, ORIGEM,
             "Notas: métricas e painel (a) obtidos por validação cruzada, com voluntários separados entre treino e teste.",
             "Ensaio positivo: ao menos uma janela com probabilidade maior ou igual ao limiar; não mede atraso ou alarmes/hora.",
             "Painel (b): importâncias do modelo final treinado em todos os dados; não são métricas de validação nem efeitos causais.",
             "Importâncias arredondadas no relatório; a soma apresentada pode diferir de 1. Quedas positivas; atividades negativas.",
             f"VP (verdadeiro positivo): {vp}; FN (falso negativo): {fn}; FP (falso positivo): {fp}; VN (verdadeiro negativo): {vn}."]
    for indice, texto in enumerate(notas):
        fig.text(0.04, 0.19 - indice * 0.024, texto, ha="left", fontsize=10)
    salvar(fig, "metricas_modelo")


def salvar(fig, nome):
    for ext in ("png", "svg", "pdf"):
        fig.savefig(os.path.join(PASTA, f"{nome}.{ext}"), dpi=300, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    vp, fn, fp, vn, limiares, imp, folds, limiar = ler_relatorio()
    matriz(vp, fn, fp, vn, folds, limiar)
    painel(vp, fn, fp, vn, limiares, imp, folds, limiar)
    print(f"VP={vp} FN={fn} FP={fp} VN={vn}; imagens em", PASTA)
