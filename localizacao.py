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
JANELA_S = 4.0        # mediana do RSSI nesse intervalo
VALIDADE_S = 6.0      # anchor sem leitura há mais que isso não entra na conta
HISTERESE_M = 0.6     # só troca de quadrante se passar da divisa por mais que isso
CONFIRMACAO_S = 3.0
RETENCAO_S = 6.0
FRESCOR_S = 2.0
ERRO_MAX_M = LADO_M * 0.25
SALTO_RSSI_DB = 8.0

ANCHORS = {1: (LADO_M / 2, LADO_M), 2: (0.0, 0.0), 3: (LADO_M, 0.0)}
QUADRANTES = {"SE": "Superior Esquerdo", "SD": "Superior Direito",
              "IE": "Inferior Esquerdo", "ID": "Inferior Direito"}


def configurar_ambiente(lado_m, posicoes):
    """Redefine em tempo de execução o lado do ambiente (m) e as coordenadas das antenas
    {id: (x, y)}. As funções leem os globais a cada chamada, então o efeito é imediato."""
    global LADO_M, ERRO_MAX_M, ANCHORS
    lado = float(lado_m)
    if not math.isfinite(lado) or lado <= 0:
        raise ValueError("lado do ambiente deve ser positivo")
    novos = {}
    for antena, (x, y) in posicoes.items():
        x, y = float(x), float(y)
        if not (0 <= x <= lado and 0 <= y <= lado):
            raise ValueError(f"antena {antena} fora do ambiente")
        novos[int(antena)] = (x, y)
    LADO_M = lado
    ERRO_MAX_M = lado * 0.25
    ANCHORS = novos


def antenas_colineares(posicoes, tolerancia_m2=0.1):
    """True se as 3 primeiras antenas estiverem (quase) alinhadas: a trilateração fica ambígua."""
    pts = [posicoes[k] for k in sorted(posicoes)][:3]
    if len(pts) < 3:
        return True
    (x1, y1), (x2, y2), (x3, y3) = pts
    return abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2 < tolerancia_m2


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
        self.lock = threading.RLock()
        # cinto -> antena -> deque[(t, rssi)]
        self.hist = defaultdict(lambda: defaultdict(lambda: deque(maxlen=800)))
        self.ultimo_q = {}   # cinto -> último quadrante (histerese)
        self.ultima_pos = {}
        self.pendentes = {}

    def atualizar(self, cinto, antena, rssi, t, gatt=False):
        if rssi is None or antena not in ANCHORS or not math.isfinite(rssi) or not math.isfinite(t):
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

    def raios(self, cinto, agora):
        """antena -> {rssi, dist, limitado}: raio estimado agora, mesmo com menos de 3 antenas (uso visual)."""
        out = {}
        for a, r in self.rssi_suavizado(cinto, agora).items():
            bruto = rssi_para_dist(r)
            out[a] = {"rssi": round(r, 1), "dist": float(min(bruto, LADO_M * 1.5)),
                      "limitado": bool(bruto > LADO_M * 1.5)}
        return out

    def estimar(self, cinto, agora):
        """Retorna uma posição com confiança qualitativa, ou None sem posição válida recente."""
        with self.lock:
            return self._estimar(cinto, agora)

    def _reter(self, cinto, agora, motivo):
        anterior = self.ultima_pos.get(cinto)
        if anterior is None or agora - anterior[1] > RETENCAO_S:
            return None
        return {**anterior[0], "confianca": "baixa", "motivo": motivo,
                "retida": True, "idade_s": max(0.0, agora - anterior[1])}

    def _estimar(self, cinto, agora):
        rssi = self.rssi_suavizado(cinto, agora)
        if len(rssi) < 3:
            self.pendentes.pop(cinto, None)
            return self._reter(cinto, agora, "Menos de 3 antenas com leituras recentes")
        ids = sorted(rssi)
        t_dados = min(self.hist[cinto][antena][-1][0] for antena in ids)
        if agora - t_dados > FRESCOR_S:
            self.pendentes.pop(cinto, None)
            return self._reter(cinto, agora, "Leituras desatualizadas")
        P = np.array([ANCHORS[i] for i in ids])
        d = np.array([rssi_para_dist(rssi[i]) for i in ids])
        fora_da_faixa = bool(np.any(d > LADO_M * 1.5))
        d = np.clip(d, 0.3, LADO_M * 1.5)

        # chute inicial: centroide ponderado (robusto a calibração ruim)
        w = 1.0 / d ** 2
        x0 = (P * w[:, None]).sum(0) / w.sum()

        def res(p):
            return np.hypot(P[:, 0] - p[0], P[:, 1] - p[1]) - d
        sol = least_squares(res, x0, bounds=([0, 0], [LADO_M, LADO_M]))
        x, y = sol.x
        erro = float(np.sqrt(np.mean(sol.fun ** 2)))
        if fora_da_faixa or not sol.success or erro > ERRO_MAX_M:
            self.pendentes.pop(cinto, None)
            return self._reter(cinto, agora, "RSSI incompatível com a geometria do ambiente")
        q = quadrante(x, y, self.ultimo_q.get(cinto))
        anterior = self.ultima_pos.get(cinto)
        if anterior is not None and agora - anterior[1] > RETENCAO_S:
            self.ultima_pos.pop(cinto, None)
            self.ultimo_q.pop(cinto, None)
            self.pendentes.pop(cinto, None)
            anterior = None
            q = quadrante(x, y)
        salto = anterior is not None and any(
            abs(rssi[antena] - anterior[0]["rssi"][antena]) >= SALTO_RSSI_DB
            for antena in ids if antena in anterior[0]["rssi"])
        if anterior is not None and (q != anterior[0]["quadrante"] or salto):
            pendente = self.pendentes.get(cinto)
            if pendente is None or pendente[0] != q:
                self.pendentes[cinto] = (q, t_dados)
            if t_dados - self.pendentes[cinto][1] < CONFIRMACAO_S:
                return self._reter(cinto, agora, "Aguardando confirmação de mudança na localização")
        self.pendentes.pop(cinto, None)
        self.ultimo_q[cinto] = q
        pos = {"x": float(x), "y": float(y), "quadrante": q, "nome": QUADRANTES[q],
               "distancias": dict(zip(ids, d.round(2).tolist())),
               "rssi": {i: round(rssi[i], 1) for i in ids},
               "n_anchors": len(ids), "erro_m": erro,
               "mais_perto": max(rssi, key=rssi.get), "confianca": "boa",
               "motivo": "Leituras consistentes", "retida": False,
               "idade_s": max(0.0, agora - t_dados)}
        self.ultima_pos[cinto] = (pos, t_dados)
        return pos
