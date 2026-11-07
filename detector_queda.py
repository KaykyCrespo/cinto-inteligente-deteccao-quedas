"""
Detecção de queda em tempo real no PC a partir das leituras cruas do MPU6050 a 100 Hz
(cinto_mvp_v1 via GATT -> antena -> MQTT). O PC monta as janelas, calcula as 8 features
(features.py) e roda o Random Forest treinado no SisFall.
"""
import time
from collections import defaultdict, deque
import numpy as np
import joblib
from features import NAMES, window_features, tamanhos


class DetectorQuedaStream:
    """
    Uso (no on_message da interface_mvp_2.py):
        det = DetectorQuedaStream("modelo_mvp_8g.joblib")
        j = det.adicionar(id_cinto, id_antena, rssi, (ax, ay, az, gx, gy, gz), seq=None)
        if j and j["queda"]: ...alarme...

    adicionar() devolve None na maioria das amostras e um dict a cada 0,5 s
    (uma janela nova de 2,5 s), com prob, features e "queda" (True/False).

    Conversão cru -> unidades: usa a faixa com que o modelo foi treinado
    (±2 g -> 16384 LSB/g, ±8 g -> 4096; ±250 °/s -> 131, ±2000 -> 16,4).
    A faixa configurada no MPU6050 do cinto PRECISA ser a mesma do modelo.
    """

    def __init__(self, caminho_modelo, limiar=None, silencio_s=5.0, reset_gap_s=0.3):
        pacote = joblib.load(caminho_modelo)
        self.model = pacote["model"]
        self.fs = pacote.get("fs", 100)
        self.faixa_acc = pacote.get("faixa_acc", 8.0)
        self.faixa_giro = pacote.get("faixa_giro", 2000.0)
        self.lsb_g = 32768.0 / self.faixa_acc
        self.lsb_dps = 32768.0 / self.faixa_giro
        self.limiar = pacote.get("limiar", 0.5) if limiar is None else limiar
        self.win, self.step, _ = tamanhos(self.fs)
        self.silencio_s = silencio_s
        self.reset_gap = max(2, int(reset_gap_s * self.fs))
        self.buf = defaultdict(lambda: deque(maxlen=self.win))
        self.desde = defaultdict(int)
        self.ultimo_seq = {}
        self.vistos = defaultdict(lambda: deque(maxlen=512))
        self.antena_ativa = {}          # sem seq: segue uma antena só (evita amostras duplicadas)
        self.t_antena = {}
        self.t_ultima = {}
        self.rssi = defaultdict(dict)
        self.ultimo_alarme = defaultdict(lambda: -1e9)
        self.amostras = defaultdict(int)
        self.perdidas = defaultdict(int)
        self.resets = defaultdict(int)

    def _reset(self, cinto):
        self.buf[cinto].clear()
        self.desde[cinto] = 0
        self.resets[cinto] += 1

    def atualizar_rssi(self, cinto, antena, rssi):
        """RSSI vindo só do anúncio BLE (antena sem GATT): conta para a âncora mais próxima,
        mas não entra na janela de amostras."""
        if rssi is not None:
            self.rssi[cinto][antena] = rssi

    def adicionar(self, cinto, antena, rssi, raw, seq=None, agora=None):
        agora = time.time() if agora is None else agora
        if rssi is not None:
            self.rssi[cinto][antena] = rssi

        if seq is not None:
            if seq in self.vistos[cinto]:
                return None                       # mesma amostra vinda de outra antena
            self.vistos[cinto].append(seq)
            if cinto in self.ultimo_seq:
                gap = (seq - self.ultimo_seq[cinto]) % 65536
                if gap == 0 or gap > 32768:
                    return None                   # atrasada / fora de ordem
                if gap > 1:
                    self.perdidas[cinto] += gap - 1
                    if gap > self.reset_gap:
                        self._reset(cinto)        # buraco grande: janela não seria contínua
            self.ultimo_seq[cinto] = seq
        else:
            ativa = self.antena_ativa.get(cinto)
            if ativa is None or (antena != ativa and agora - self.t_antena.get(cinto, 0) > 1.0):
                self.antena_ativa[cinto] = ativa = antena
            if antena != ativa:
                return None
            self.t_antena[cinto] = agora
            # sem contador, só dá para perceber buracos pelo relógio do PC (chega em rajadas)
            if cinto in self.t_ultima and agora - self.t_ultima[cinto] > 0.5:
                self._reset(cinto)
            self.t_ultima[cinto] = agora

        ax, ay, az, gx, gy, gz = raw
        self.buf[cinto].append((ax / self.lsb_g, ay / self.lsb_g, az / self.lsb_g,
                                gx / self.lsb_dps, gy / self.lsb_dps, gz / self.lsb_dps))
        self.amostras[cinto] += 1
        self.desde[cinto] += 1
        if len(self.buf[cinto]) < self.win or self.desde[cinto] < self.step:
            return None
        self.desde[cinto] = 0

        w = np.asarray(self.buf[cinto], dtype=np.float32)
        f = window_features(w[:, :3], w[:, 3:], self.fs)
        prob = float(self.model.predict_proba(f.reshape(1, -1))[0, 1])
        queda = prob >= self.limiar and agora - self.ultimo_alarme[cinto] > self.silencio_s
        if queda:
            self.ultimo_alarme[cinto] = agora
        ant = max(self.rssi[cinto], key=self.rssi[cinto].get) if self.rssi[cinto] else antena
        return {"belt": cinto, "prob": prob, "queda": queda, "anchor": ant,
                "features": dict(zip(NAMES, np.round(f, 3).tolist()))}

    def taxa_perda(self, cinto):
        a, p = self.amostras[cinto], self.perdidas[cinto]
        return p / (a + p) if a + p else 0.0
