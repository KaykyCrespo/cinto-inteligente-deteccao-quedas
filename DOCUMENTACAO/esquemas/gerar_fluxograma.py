"""Gera o fluxograma do funcionamento completo do sistema (MVP) em PNG e SVG.

Uso: python DOCUMENTACAO/esquemas/gerar_fluxograma.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon

PASTA = os.path.dirname(os.path.abspath(__file__))

AZUL = "#2f6fd6"
TEXTO = "#1f3a5f"
CAIXA = "#e8f0fb"
FUNDO = "#f5f7fa"
BORDA_FUNDO = "#c9d3e0"
AMARELO, BORDA_AMARELO = "#fdf3d0", "#c9a227"
VERDE, BORDA_VERDE = "#e3f4e6", "#3c9a52"
ESCURO = "#1c2333"

fig, ax = plt.subplots(figsize=(9.5, 12.2))
ax.set_xlim(0, 100)
ax.set_ylim(-10, 112)
ax.set_aspect("equal")
ax.axis("off")


def caixa(x0, y0, x1, y1, titulo, texto="", fundo=CAIXA, borda=AZUL, cor=TEXTO, raio=1.2, tam=9.5):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle=f"round,pad=0,rounding_size={raio}",
                                fc=fundo, ec=borda, lw=1.3, zorder=3))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    linhas = [(t, True) for t in titulo.split("\n")] + [(t, False) for t in texto.split("\n") if texto]
    passo = 1.85
    y = cy + (len(linhas) - 1) * passo / 2
    for t, negrito in linhas:
        ax.text(cx, y, t, ha="center", va="center", fontsize=tam if negrito else tam - 1,
                fontweight="bold" if negrito else "normal", color=cor, zorder=4)
        y -= passo


def regiao(x0, y0, x1, y1, titulo):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=1.5",
                                fc=FUNDO, ec=BORDA_FUNDO, lw=1.0, ls="--", zorder=1))
    ax.text(x0 + 1.2, y1 - 1.6, titulo, ha="left", va="center", fontsize=9, fontweight="bold", color=TEXTO,
            zorder=2)


def seta(pontos, tracejada=False):
    xs, ys = zip(*pontos)
    ax.plot(xs[:-1] + (xs[-1],), ys[:-1] + (ys[-1],), color=AZUL, lw=1.4, ls="--" if tracejada else "-",
            zorder=2, solid_capstyle="butt")
    ax.annotate("", xy=pontos[-1], xytext=pontos[-2],
                arrowprops=dict(arrowstyle="-|>", color=AZUL, lw=1.4, mutation_scale=12,
                                shrinkA=0, shrinkB=0), zorder=5)


def etiqueta(x, y, texto):
    ax.text(x, y, texto, ha="center", va="center", fontsize=8, fontweight="bold", color=TEXTO, zorder=6,
            bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.8", fc="white", ec=AZUL, lw=1.0))


# ---------- início ----------
caixa(5, 104, 47, 110.5, "Início", "usuário veste o cinto e liga o dispositivo", fundo=ESCURO, borda=ESCURO,
      cor="white", raio=3.2)

# ---------- 1 cinto ----------
regiao(2, 30, 50, 101.5, "(1) Cinto")
caixa(12, 92, 40, 98.5, "ESP32-C3 Super Mini", "inicia sensores e BLE")
caixa(9, 80.5, 43, 86.5, "Ciclo de leitura a 100 Hz", "a cada 10 ms")
caixa(3.5, 64.5, 25, 75.5, "MPU6050 (I²C)", "aceleração + giroscópio\n±8 g / ±2000 °/s")
caixa(27, 64.5, 48.5, 75.5, "AD8232 + eletrodos", "sinal de ECG (ADC)\n+ eletrodo solto")
caixa(6, 51, 46, 59.5, "Monta o pacote", "leituras brutas dos 6 eixos,\nestado dos eletrodos e ECG")
caixa(4.5, 34, 47.5, 45, "Transmite por BLE",
      "GATT (notify, 100 Hz) → antena conectada\nAdvertising (100 ms) → todas as antenas")

seta([(26, 104), (26, 98.5)])
seta([(26, 92), (26, 86.5)])
ax.plot([26, 26], [80.5, 78], color=AZUL, lw=1.4, zorder=2)
ax.plot([14.25, 37.75], [78, 78], color=AZUL, lw=1.4, zorder=2)
seta([(14.25, 78), (14.25, 75.5)])
seta([(37.75, 78), (37.75, 75.5)])
seta([(14.25, 64.5), (14.25, 59.5)])
seta([(37.75, 64.5), (37.75, 59.5)])
seta([(26, 51), (26, 45)])

# ---------- 2 ambiente ----------
regiao(53, 79.5, 98.5, 111, "(2) Ambiente")
ax.add_patch(Polygon([(55, 81.5), (97, 81.5), (76, 109.5)], closed=True, fc=CAIXA, ec=AZUL, lw=1.3, zorder=2))
caixa(70, 97, 82, 101.5, "anchor01", tam=9)
ax.text(76, 92.3, "uma antena recebe os dados\npor GATT; todas medem\no RSSI do anúncio",
        ha="center", va="center", fontsize=7.4, color=TEXTO, zorder=4, linespacing=1.3)
caixa(60, 83.5, 73.5, 88, "anchor02", tam=9)
caixa(78.5, 83.5, 92, 88, "anchor03", tam=9)

seta([(26, 34), (26, 27), (51.5, 27), (51.5, 85.75), (60, 85.75)])
etiqueta(38.5, 27, "sinal BLE")

# ---------- 3 computador ----------
regiao(53, 4, 98.5, 76.5, "(3) Computador")
caixa(58, 66.5, 94, 72.5, "Broker Mosquitto (Windows)", "tópicos oqpnb/anchor/<id>")
caixa(58, 57, 94, 63, "Sistema central (app.py)", "ingestão MQTT · painel Streamlit · SQLite")
seta([(76, 81.5), (76, 72.5)])
etiqueta(76, 78, "Wi-Fi / MQTT")
seta([(76, 66.5), (76, 63)])

regiao(55, 6, 97, 54.5, "(4) Análise")
caixa(57, 36, 76, 50.5, "Classificador\nde quedas", "janelas de 2,5 s\n8 atributos\nRandom Forest\n(base SisFall)", tam=9)
caixa(80, 36, 96.3, 50.5, "Localização\nindoor", "RSSI → distância\n(log-distância)\nquadrante pelas\n3 antenas", tam=9)
ax.plot([76, 76], [57, 54.5], color=AZUL, lw=1.4, zorder=2)
ax.plot([66.5, 88.15], [54.5, 54.5], color=AZUL, lw=1.4, zorder=2)
seta([(66.5, 54.5), (66.5, 50.5)])
seta([(88.15, 54.5), (88.15, 50.5)])

ax.add_patch(Polygon([(66.5, 33.5), (74.5, 28), (66.5, 22.5), (58.5, 28)], closed=True, fc=AMARELO,
                     ec=BORDA_AMARELO, lw=1.3, zorder=3))
ax.text(66.5, 28, "Probabilidade\n≥ limiar?", ha="center", va="center", fontsize=8, color=TEXTO, zorder=4)
seta([(66.5, 36), (66.5, 33.5)])

caixa(80, 23.5, 96.3, 32.5, "Alerta de queda", "painel + Telegram\n(com o quadrante)", fundo=VERDE,
      borda=BORDA_VERDE, raio=4, tam=8.5)
seta([(74.5, 28), (80, 28)])
etiqueta(77.2, 30.6, "Sim")
seta([(88.15, 36), (88.15, 32.5)], tracejada=True)

caixa(57.5, 9, 75.5, 17.5, "Grava no SQLite", "e continua\nmonitorando", tam=9)
seta([(66.5, 22.5), (66.5, 17.5)])
etiqueta(66.5, 20, "Não")
seta([(88.15, 23.5), (88.15, 13.25), (75.5, 13.25)])

seta([(66.5, 9), (66.5, 1), (0.8, 1), (0.8, 83.5), (9, 83.5)])
etiqueta(33, 1, "novo ciclo de leitura")

# ---------- legenda ----------
ly = -5
ax.plot([2, 98], [-2, -2], color=BORDA_FUNDO, lw=0.8, ls=":")
itens = [
    (ESCURO, ESCURO, "Início / entrada", 2), (CAIXA, AZUL, "Sinal / dados", 24),
    (AMARELO, BORDA_AMARELO, "Decisão (Sim/Não)", 46), (VERDE, BORDA_VERDE, "Resultado", 70),
]
for fc, ec, txt, x in itens:
    ax.add_patch(FancyBboxPatch((x, ly - 1), 3, 2, boxstyle="round,pad=0,rounding_size=0.5", fc=fc, ec=ec, lw=1.1))
    ax.text(x + 4, ly, txt, va="center", fontsize=8.5, color=TEXTO)
ax.add_patch(FancyBboxPatch((2, ly - 4.6), 3, 2, boxstyle="round,pad=0,rounding_size=0.5", fc=FUNDO,
                            ec=BORDA_FUNDO, lw=1.0, ls="--"))
ax.text(6, ly - 3.6, "Etapa do sistema", va="center", fontsize=8.5, color=TEXTO)
ax.annotate("", xy=(29, ly - 3.6), xytext=(24, ly - 3.6),
            arrowprops=dict(arrowstyle="-|>", color=AZUL, lw=1.4, mutation_scale=12))
ax.text(30, ly - 3.6, "Fluxo de sinal / dados", va="center", fontsize=8.5, color=TEXTO)
ax.plot([56, 61], [ly - 3.6, ly - 3.6], color=AZUL, lw=1.4, ls="--")
ax.text(62, ly - 3.6, "Informação complementar", va="center", fontsize=8.5, color=TEXTO)

for ext in ("png", "svg"):
    fig.savefig(os.path.join(PASTA, f"fluxograma_sistema.{ext}"), dpi=200, bbox_inches="tight", facecolor="white")
print("Fluxograma gerado em", PASTA)
