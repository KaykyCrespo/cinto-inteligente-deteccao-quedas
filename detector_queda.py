"""
Detecção de queda em tempo real no PC, a partir dos pacotes versão 3 do cinto.

Integração com a interface.py (no callback on_message do MQTT):

    from detector_queda import DetectorQueda
    detector = DetectorQueda("modelo_queda.joblib")
    ...
    j = detector.processar(payload_json)   # dict já decodificado do MQTT
    if j and j["queda"]:
        print(f"*** QUEDA DETECTADA *** cinto {j['belt']} "
              f"prob {j['prob']:.2f} perto da âncora {j['anchor']}")

processar() devolve None para pacotes que não são de janela ou que já foram
vistos (a mesma janela chega por várias âncoras e várias vezes). Para cada
janela nova devolve um dict com prob, features e "queda" (True/False).

A âncora precisa publicar os pacotes versão 3 com os 8 valores em "feat"
(lista de int16) e o "win_seq", ou então o Manufacturer Data em hexadecimal
no campo "raw" (24 bytes). Os dois formatos são aceitos.
"""
import struct, time
from collections import defaultdict, deque
import numpy as np
import joblib
from features import from_int16, NAMES


def decode_raw(hexstr):
    b = bytes.fromhex(hexstr.replace(":", "").replace(" ", ""))
    i = b.find(b"OQPNB")
    if i < 0 or len(b) < i + 24 or b[i + 5] != 3:
        return None
    belt, win_seq = b[i + 6], b[i + 7]
    feat = struct.unpack("<8h", b[i + 8:i + 24])
    return belt, win_seq, feat


class DetectorQueda:
    def __init__(self, caminho_modelo, limiar=None, janelas_para_alarme=1, silencio_s=10.0):
        pacote = joblib.load(caminho_modelo)
        self.model = pacote["model"]
        self.limiar = pacote.get("limiar", 0.5) if limiar is None else limiar
        self.n_alarme = janelas_para_alarme
        self.silencio_s = silencio_s
        self.vistos = defaultdict(lambda: deque(maxlen=64))  # win_seq já processados por cinto
        self.seguidas = defaultdict(int)
        self.ultimo_alarme = defaultdict(lambda: -1e9)
        self.rssi = defaultdict(dict)  # belt -> {anchor: rssi da última janela}
        self.recebidas = defaultdict(int)  # janelas novas por cinto
        self.perdidas = defaultdict(int)   # janelas que nunca chegaram (buracos no win_seq)
        self.ultimo_seq = {}

    def _extrair(self, msg):
        if msg.get("raw"):
            r = decode_raw(msg["raw"])
            if r: return r
        if "feat" in msg and "win_seq" in msg:
            return msg.get("belt_num", 1), int(msg["win_seq"]), msg["feat"]
        return None

    def processar(self, msg, agora=None):
        """Recebe um payload JSON (dict). Retorna None ou um dict da janela nova."""
        r = self._extrair(msg)
        if r is None:
            return None
        belt, win_seq, feat = r
        agora = time.time() if agora is None else agora
        if "anchor" in msg and "rssi" in msg:
            self.rssi[belt][msg["anchor"]] = msg["rssi"]
        if win_seq in self.vistos[belt]:          # mesma janela vinda de outra âncora / repetição
            return None
        self.vistos[belt].append(win_seq)
        if belt in self.ultimo_seq:
            gap = (win_seq - self.ultimo_seq[belt]) % 256
            if 1 < gap < 128:
                self.perdidas[belt] += gap - 1
        self.ultimo_seq[belt] = win_seq
        self.recebidas[belt] += 1

        x = from_int16(feat).reshape(1, -1)
        prob = float(self.model.predict_proba(x)[0, 1])
        self.seguidas[belt] = self.seguidas[belt] + 1 if prob >= self.limiar else 0
        queda = False
        if self.seguidas[belt] >= self.n_alarme and agora - self.ultimo_alarme[belt] > self.silencio_s:
            self.ultimo_alarme[belt] = agora
            queda = True
        ancora = max(self.rssi[belt], key=self.rssi[belt].get) if self.rssi[belt] else msg.get("anchor")
        return {"belt": belt, "win_seq": win_seq, "prob": prob, "queda": queda, "anchor": ancora,
                "features": dict(zip(NAMES, x[0].round(3).tolist()))}

    def taxa_perda(self, belt):
        r, p = self.recebidas[belt], self.perdidas[belt]
        return p / (r + p) if r + p else 0.0


# =====================================================================
# MVP: dados CRUS do MPU6050 a 100 Hz (cinto_mvp via GATT -> antena -> MQTT)
# O PC monta as janelas, calcula as features e roda o RF.
# =====================================================================
from features import window_features, tamanhos


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

    def __init__(self, caminho_modelo, limiar=None, silencio_s=10.0, reset_gap_s=0.3):
        pacote = joblib.load(caminho_modelo)
        self.model = pacote["model"]
        self.fs = pacote.get("fs", 50)
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
