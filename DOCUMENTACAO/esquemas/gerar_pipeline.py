"""Gera o diagrama do pipeline de IA (treino offline e inferência em tempo real) em PNG e SVG.

Uso: python DOCUMENTACAO/esquemas/gerar_pipeline.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PASTA = os.path.dirname(os.path.abspath(__file__))

AZUL = "#2f6fd6"
TEXTO = "#1f3a5f"
FUNDO = "#f5f7fa"
BORDA_FUNDO = "#c9d3e0"
CORES = {"dado": "#e8f0fb", "proc": "#ffffff", "modelo": "#f1e8fb", "saida": "#e3f4e6", "decisao": "#fdf3d0"}

TREINO = [
    ("dado", "Dataset SisFall", "38 voluntários\n200 Hz, cintura"),
    ("proc", "Adaptação", "ao cinto: 100 Hz\n±8 g · ±2000 °/s"),
    ("proc", "Janelas", "2,5 s, passo 0,5 s\n122.572 janelas"),
    ("proc", "8 atributos", "features.py\n(magnitudes)"),
    ("modelo", "Random Forest", "scikit-learn\n200 árvores"),
    ("decisao", "Validação", "GroupKFold (5)\npor voluntário"),
    ("saida", "Modelo salvo", "joblib\nmodelo_mvp_8g"),
]
OPERACAO = [
    ("dado", "Cinto", "MPU6050 100 Hz\nvia BLE → MQTT"),
    ("proc", "Buffer por cinto", "detector_queda.py"),
    ("proc", "Janelas", "2,5 s a cada 0,5 s"),
    ("proc", "8 atributos", "mesma função\ndo treino"),
    ("modelo", "Modelo", "joblib\npredict_proba"),
    ("decisao", "Probabilidade\n≥ limiar?", "padrão 0,50"),
    ("saida", "Alerta", "painel · Telegram\nregistro no SQLite"),
]

LARG, ALT, PASSO = 12.2, 9.0, 14.3
fig, ax = plt.subplots(figsize=(15, 6.6))
ax.set_xlim(-1, 101)
ax.set_ylim(-3, 45)
ax.set_aspect("equal")
ax.axis("off")


def faixa(y0, y1, titulo):
    ax.add_patch(FancyBboxPatch((-0.5, y0), 101, y1 - y0, boxstyle="round,pad=0,rounding_size=1.5",
                                fc=FUNDO, ec=BORDA_FUNDO, lw=1.0, ls="--"))
    ax.text(0.6, y1 - 1.6, titulo, ha="left", va="center", fontsize=11, fontweight="bold", color=TEXTO)


def linha(etapas, yc):
    centros = []
    for k, (tipo, tit, sub) in enumerate(etapas):
        x = 0.8 + k * PASSO
        ax.add_patch(FancyBboxPatch((x, yc - ALT / 2), LARG, ALT, boxstyle="round,pad=0,rounding_size=1",
                                    fc=CORES[tipo], ec=AZUL, lw=1.2))
        n_tit = tit.count("\n") + 1
        ax.text(x + LARG / 2, yc + 1.6 + (0.7 if n_tit > 1 else 0), tit, ha="center", va="center", fontsize=9.5,
                fontweight="bold", color=TEXTO, linespacing=1.2)
        ax.text(x + LARG / 2, yc - 1.9, sub, ha="center", va="center", fontsize=7.8, color=TEXTO, linespacing=1.3)
        if k:
            ax.annotate("", xy=(x, yc), xytext=(x - (PASSO - LARG), yc),
                        arrowprops=dict(arrowstyle="-|>", color=AZUL, lw=1.4, mutation_scale=11))
        centros.append(x + LARG / 2)
    return centros


faixa(23, 44.5, "Treino (offline, uma vez) — scripts/treino_sisfall.py")
c_treino = linha(TREINO, 32.5)
faixa(-2.5, 19, "Operação em tempo real — app.py / detector_queda.py")
c_op = linha(OPERACAO, 7.5)

for idx, rotulo, dx, alinhar in ((3, "mesma função de atributos", -0.8, "right"),
                                (6, "modelo salvo é carregado aqui", 1.2, "left")):
    xt, xo = c_treino[idx], c_op[idx if idx != 6 else 4]
    ax.annotate("", xy=(xo, 12.0), xytext=(xt, 28.0),
                arrowprops=dict(arrowstyle="-|>", color=AZUL, lw=1.3, ls="--", mutation_scale=11,
                                connectionstyle="arc3,rad=0"))
    ax.text((xt + xo) / 2 + dx, 20.8, rotulo, ha=alinhar, va="center", fontsize=8,
            style="italic", color=TEXTO, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"))

for ext in ("png", "svg"):
    fig.savefig(os.path.join(PASTA, f"pipeline_ia.{ext}"), dpi=200, bbox_inches="tight", facecolor="white")
print("Pipeline gerado em", PASTA)
