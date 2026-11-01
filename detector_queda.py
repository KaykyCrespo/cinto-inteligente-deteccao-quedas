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
