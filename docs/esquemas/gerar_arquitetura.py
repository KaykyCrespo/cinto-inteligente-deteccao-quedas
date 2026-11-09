"""Gera o diagrama de arquitetura em camadas (PNG e SVG).

Uso: python docs/esquemas/gerar_arquitetura.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

PASTA = os.path.dirname(os.path.abspath(__file__))

AZUL = "#2f6fd6"
TEXTO = "#1f3a5f"
CAIXA = "#ffffff"

CAMADAS = [
    ("1. Borda", "#e8f0fb", [
        ("Cinto ESP32-C3", "Super Mini\nleitura a 100 Hz"),
        ("MPU6050", "I²C 400 kHz\n±8 g / ±2000 °/s"),
        ("AD8232", "ECG (ADC)\neletrodo solto (GPIO)"),
        ("Alimentação", "18650 · TP4056\nMT3608 (5 V)"),
    ]),
    ("2. Conectividade", "#e6f4f1", [
        ("Antenas anchor01–03", "ESP32 DevKit V1 · BLE → Wi-Fi"),
        ("Rede Wi-Fi", "2,4 GHz · TCP/IP"),
        ("Broker Mosquitto", "MQTT · porta 1883"),
    ]),
    ("3. Persistência", "#fdf3d0", [
        ("SQLite", "dados/oqpnb.db · 7 tabelas"),
        ("Gravações CSV", "dados/gravacoes"),
        ("Ambiente", "dados/ambiente.json"),
    ]),
    ("4. Inteligência", "#f1e8fb", [
        ("Detector de quedas", "janelas 2,5 s · 8 atributos"),
        ("Random Forest", "200 árvores · treinado no SisFall"),
        ("Localização indoor", "RSSI → distância → quadrante"),
    ]),
    ("5. Interface", "#e3f4e6", [
        ("Painel Streamlit", "Monitoramento e Detalhes · :8501"),
        ("Alerta Telegram", "bot · HTTPS"),
        ("Exportação", "CSV por sessão e arquivo .db"),
    ]),
]

LIGACOES = [
    "BLE 5: GATT (100 Hz, antena conectada) + Advertising (RSSI, todas as antenas)",
    "MQTT oqpnb/anchor/<id> · ingestão pelo app.py · gravação em lote (WAL)",
    "janelas, quedas e status lidos e gravados em SQL",
    "probabilidade, quadrante e alertas",
]

ALT, GAP, X0, X1, ROT = 15.0, 7.0, 0.0, 100.0, 19.0
total = len(CAMADAS) * ALT + (len(CAMADAS) - 1) * GAP

fig, ax = plt.subplots(figsize=(11, 11 * (total + 2) / 102))
ax.set_xlim(-1, 101)
ax.set_ylim(-1, total + 1)
ax.set_aspect("equal")
ax.axis("off")

for i, (nome, cor, itens) in enumerate(CAMADAS):
    y1 = total - i * (ALT + GAP)
    y0 = y1 - ALT
    ax.add_patch(FancyBboxPatch((X0, y0), X1 - X0, ALT, boxstyle="round,pad=0,rounding_size=1.5",
                                fc=cor, ec=AZUL, lw=1.3))
    ax.text(X0 + ROT / 2, (y0 + y1) / 2, nome.replace(". ", ".\n"), ha="center", va="center", fontsize=11,
            fontweight="bold", color=TEXTO, linespacing=1.4)
    n = len(itens)
    larg = (X1 - X0 - ROT - 2 - (n - 1) * 1.5) / n
    for j, (tit, sub) in enumerate(itens):
        bx = X0 + ROT + j * (larg + 1.5)
        ax.add_patch(FancyBboxPatch((bx, y0 + 2.5), larg, ALT - 5, boxstyle="round,pad=0,rounding_size=1",
                                    fc=CAIXA, ec=AZUL, lw=1.0))
        cy = y0 + ALT / 2
        dois = "\n" in sub
        ax.text(bx + larg / 2, cy + (2.2 if dois else 1.4), tit, ha="center", va="center", fontsize=9.5,
                fontweight="bold", color=TEXTO)
        ax.text(bx + larg / 2, cy - (1.8 if dois else 1.6), sub, ha="center", va="center", fontsize=7.6,
                color=TEXTO, linespacing=1.4)
    if i < len(LIGACOES):
        ax.annotate("", xy=(X0 + ROT / 2, y0 - GAP), xytext=(X0 + ROT / 2, y0),
                    arrowprops=dict(arrowstyle="-|>", color=AZUL, lw=1.6, mutation_scale=14))
        ax.text(X0 + ROT / 2 + 3, y0 - GAP / 2, LIGACOES[i], ha="left", va="center", fontsize=8.5,
                color=TEXTO, style="italic")

for ext in ("png", "svg"):
    fig.savefig(os.path.join(PASTA, f"arquitetura_camadas.{ext}"), dpi=200, bbox_inches="tight", facecolor="white")
print("Arquitetura gerada em", PASTA)
