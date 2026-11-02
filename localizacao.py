"""
localizacao.py - Estima em qual quadrante do ambiente o cinto está, a partir do
RSSI medido pelas 3 anchors.

Geometria (quadrado de lado LADO_M, origem no canto inferior esquerdo):

        A1 (L/2, L)
    +-------+-------+
    |  SE   |  SD   |      SE = Superior Esquerdo   SD = Superior Direito
    +-------+-------+
    |  IE   |  ID   |      IE = Inferior Esquerdo   ID = Inferior Direito
    +-------+-------+
  A2 (0,0)        A3 (L,0)

Modelo RSSI -> distância (log-distance):
    d = 10 ** ((RSSI_1M - rssi) / (10 * N))
Calibração: teste a 5 m deu RSSI ~ -76 dBm; com RSSI_1M = -62 => N = 2,0.

Posição: mínimos quadrados sobre (x-xi)^2 + (y-yi)^2 = di^2, limitado ao quadrado,
com chute inicial no centroide ponderado por 1/di^2. RSSI suavizado pela mediana
dos últimos JANELA_S segundos de cada anchor (GATT ou anúncio).
"""
import math
import os
import threading
from collections import defaultdict, deque

import numpy as np
from scipy.optimize import least_squares

LADO_M = float(os.environ.get("OQPNB_LADO_M", "5.0"))
RSSI_1M = float(os.environ.get("OQPNB_RSSI_1M", "-62"))
N_PERDA = float(os.environ.get("OQPNB_N_PERDA", "2.0"))
OFFSET_GATT_DB = float(os.environ.get("OQPNB_OFFSET_GATT", "0"))  # rssi_gatt + offset ~ rssi_anuncio
JANELA_S = 3.0        # mediana do RSSI nesse intervalo
VALIDADE_S = 6.0      # anchor sem leitura há mais que isso não entra na conta
HISTERESE_M = 0.4     # só troca de quadrante se passar da divisa por mais que isso

ANCHORS = {1: (LADO_M / 2, LADO_M), 2: (0.0, 0.0), 3: (LADO_M, 0.0)}
QUADRANTES = {"SE": "Superior Esquerdo", "SD": "Superior Direito",
              "IE": "Inferior Esquerdo", "ID": "Inferior Direito"}


def rssi_para_dist(rssi):
    return 10 ** ((RSSI_1M - rssi) / (10 * N_PERDA))


def quadrante(x, y, anterior=None):
    """Quadrante de (x, y). Com `anterior`, mantém o quadrante atual enquanto o ponto
    não ultrapassar a divisa por mais de HISTERESE_M."""
    meio = LADO_M / 2
    col = "E" if x < meio else "D"
    lin = "S" if y >= meio else "I"
    if anterior:
        if abs(x - meio) < HISTERESE_M:
            col = anterior[1]
        if abs(y - meio) < HISTERESE_M:
            lin = anterior[0]
    return lin + col


class Localizador:
    def __init__(self):
        self.lock = threading.Lock()
        # cinto -> antena -> deque[(t, rssi)]
        self.hist = defaultdict(lambda: defaultdict(lambda: deque(maxlen=400)))
        self.ultimo_q = {}   # cinto -> último quadrante (histerese)

    def atualizar(self, cinto, antena, rssi, t, gatt=False):
        if rssi is None or antena not in ANCHORS:
            return
        if gatt:
            rssi = rssi + OFFSET_GATT_DB
        with self.lock:
            self.hist[cinto][antena].append((t, rssi))

    def rssi_suavizado(self, cinto, agora):
        """antena -> mediana do RSSI nos últimos JANELA_S s (só anchors com leitura recente)."""
        out = {}
        with self.lock:
            for antena, h in self.hist[cinto].items():
                if not h or agora - h[-1][0] > VALIDADE_S:
                    continue
                vals = [r for t, r in h if agora - t <= JANELA_S] or [h[-1][1]]
                out[antena] = float(np.median(vals))
        return out

    def estimar(self, cinto, agora):
        """Retorna dict com x, y, quadrante, nome, distancias, rssi, n_anchors (ou None se < 2 anchors)."""
        rssi = self.rssi_suavizado(cinto, agora)
        if len(rssi) < 2:
            return None
        ids = sorted(rssi)
        P = np.array([ANCHORS[i] for i in ids])
        d = np.array([rssi_para_dist(rssi[i]) for i in ids])
        d = np.clip(d, 0.3, LADO_M * 1.5)

        # chute inicial: centroide ponderado (robusto a calibração ruim)
        w = 1.0 / d ** 2
        x0 = (P * w[:, None]).sum(0) / w.sum()

        if len(ids) >= 3:
            def res(p):
                return np.hypot(P[:, 0] - p[0], P[:, 1] - p[1]) - d
            sol = least_squares(res, x0, bounds=([0, 0], [LADO_M, LADO_M]))
            x, y = sol.x
            erro = float(np.sqrt(np.mean(sol.fun ** 2)))
        else:
            x, y = np.clip(x0, 0, LADO_M)
            erro = None
        q = quadrante(x, y, self.ultimo_q.get(cinto))
        self.ultimo_q[cinto] = q
        return {"x": float(x), "y": float(y), "quadrante": q, "nome": QUADRANTES[q],
                "distancias": dict(zip(ids, d.round(2).tolist())),
                "rssi": {i: round(rssi[i], 1) for i in ids},
                "n_anchors": len(ids), "erro_m": erro,
                "mais_perto": max(rssi, key=rssi.get)}
