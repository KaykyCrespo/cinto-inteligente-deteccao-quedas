"""Gera a matriz de confusão e o painel de métricas do modelo a partir de modelos/resultado_treino_mvp_8g.txt.

Uso: python docs/esquemas/gerar_metricas.py
"""
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PASTA = os.path.dirname(os.path.abspath(__file__))
RELATORIO = os.path.join(PASTA, "..", "..", "modelos", "resultado_treino_mvp_8g.txt")

AZUL = "#2f6fd6"
TEXTO = "#1f3a5f"
VERDE = "#3c9a52"
VERMELHO = "#c62828"


def ler_relatorio():
    with open(RELATORIO, encoding="utf-8") as f:
        txt = f.read()
    vp, quedas = map(int, re.search(r"Sensibilidade [\d.]+\s+\((\d+)/(\d+) quedas", txt).groups())
    fp, atividades = map(int, re.search(r"\((\d+) alarmes falsos em (\d+) atividades\)", txt).groups())
    limiares = [(float(a), float(b), float(c)) for a, b, c in
                re.findall(r"limiar ([\d.]+): sensibilidade ([\d.]+)\s+especificidade ([\d.]+)", txt)]
    imp = [(n, float(v)) for n, v in re.findall(r"(\w+)=([\d.]+)", txt.split("Importância das features:")[1])]
    return vp, quedas - vp, fp, atividades - fp, limiares, imp


def pct(v):
    return f"{v * 100:.1f}%".replace(".", ",")


def matriz(vp, fn, fp, vn):
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
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
            ax.text(j + 0.5, 1 - i + 0.36, f"{sigla} · {pct(frac)} da linha", ha="center", va="center", fontsize=11,
                    color="white" if escuro else TEXTO)
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.set_xticks([0.5, 1.5], ["Previsto: queda", "Previsto: atividade"], fontsize=11, color=TEXTO)
    ax.set_yticks([1.5, 0.5], [f"Real: queda\n({vp + fn:,} registros)".replace(",", "."),
                               f"Real: atividade\n({fp + vn:,} registros)".replace(",", ".")],
                  fontsize=11, color=TEXTO)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Matriz de confusão – validação cruzada por voluntário\n(GroupKFold, 5 folds, limiar 0,50, por registro)",
                 fontsize=12, color=TEXTO, fontweight="bold", pad=38)
    ax.set_aspect("equal")
    fig.text(0.5, 0.02, "Fonte: elaborado pelos autores (2026), a partir de modelos/resultado_treino_mvp_8g.txt.",
             ha="center", fontsize=8, color="#555555")
    salvar(fig, "matriz_confusao")


def painel(vp, fn, fp, vn, limiares, imp):
    rec = vp / (vp + fn)
    esp = vn / (vn + fp)
    prec = vp / (vp + fp)
    f1 = 2 * prec * rec / (prec + rec)
    acc = (vp + vn) / (vp + fn + fp + vn)

    fig = plt.figure(figsize=(12, 7.2))
    fig.suptitle("Random Forest (200 árvores, 8 atributos) – desempenho no SisFall", fontsize=15,
                 fontweight="bold", color=TEXTO, y=0.97)

    cards = [("Recall\n(sensibilidade)", rec, "VP / (VP + FN)"), ("Precisão", prec, "VP / (VP + FP)"),
             ("F1-score", f1, "2·P·R / (P + R)"), ("Especificidade", esp, "VN / (VN + FP)"),
             ("Acurácia", acc, "(VP + VN) / total")]
    topo = fig.add_axes([0.03, 0.62, 0.94, 0.27])
    topo.axis("off")
    topo.set_xlim(0, 100)
    topo.set_ylim(0, 30)
    larg = 18
    for k, (nome, valor, formula) in enumerate(cards):
        x = 1 + k * (larg + 1.75)
        topo.add_patch(FancyBboxPatch((x, 1), larg, 27, boxstyle="round,pad=0,rounding_size=1.5",
                                      fc="#e8f0fb", ec=AZUL, lw=1.3))
        topo.text(x + larg / 2, 22.5, nome, ha="center", va="center", fontsize=11, color=TEXTO, fontweight="bold")
        topo.text(x + larg / 2, 12.5, pct(valor), ha="center", va="center", fontsize=24, color=AZUL,
                  fontweight="bold")
        topo.text(x + larg / 2, 5, formula, ha="center", va="center", fontsize=9, color="#555555")

    ax1 = fig.add_axes([0.07, 0.09, 0.40, 0.42])
    lim = [l[0] for l in limiares]
    ax1.plot(lim, [l[1] * 100 for l in limiares], "o-", color=AZUL, lw=2, label="Sensibilidade")
    ax1.plot(lim, [l[2] * 100 for l in limiares], "s-", color=VERDE, lw=2, label="Especificidade")
    ax1.axvline(0.5, color="#999999", ls="--", lw=1)
    ax1.text(0.505, 90.6, "padrão 0,50", fontsize=8.5, color="#555555")
    ax1.set_ylim(90, 100.5)
    ax1.set_xlabel("Limiar de alarme (ajustável no painel)", fontsize=10, color=TEXTO)
    ax1.set_ylabel("%", fontsize=10, color=TEXTO)
    ax1.set_title("Efeito do limiar", fontsize=12, color=TEXTO, fontweight="bold")
    ax1.legend(loc="lower left", fontsize=9, frameon=False)
    ax1.grid(alpha=0.3)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    ax2 = fig.add_axes([0.60, 0.09, 0.36, 0.42])
    nomes = {"tilt": "inclinação (tilt)", "gstd": "desvio da rotação", "amax": "aceleração máxima",
             "gmax": "rotação máxima", "astd": "desvio da aceleração", "jerk": "jerk",
             "post_std": "repouso após impacto", "amin": "aceleração mínima"}
    imp = sorted(imp, key=lambda t: t[1])
    ax2.barh([nomes.get(n, n) for n, _ in imp], [v for _, v in imp], color=AZUL, alpha=0.85)
    for y, (_, v) in enumerate(imp):
        ax2.text(v + 0.005, y, f"{v:.2f}".replace(".", ","), va="center", fontsize=9, color=TEXTO)
    ax2.set_xlim(0, max(v for _, v in imp) * 1.2)
    ax2.set_title("Importância dos atributos", fontsize=12, color=TEXTO, fontweight="bold")
    ax2.tick_params(labelsize=9.5)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)

    fig.text(0.5, 0.005, f"VP = {vp} · FN = {fn} · FP = {fp} · VN = {vn} — validação cruzada por voluntário "
             "(GroupKFold, 5 folds), por registro. Fonte: elaborado pelos autores (2026).",
             ha="center", fontsize=8.5, color="#555555")
    salvar(fig, "metricas_modelo")


def salvar(fig, nome):
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(PASTA, f"{nome}.{ext}"), dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    vp, fn, fp, vn, limiares, imp = ler_relatorio()
    matriz(vp, fn, fp, vn)
    painel(vp, fn, fp, vn, limiares, imp)
    print(f"VP={vp} FN={fn} FP={fp} VN={vn}; imagens em", PASTA)
