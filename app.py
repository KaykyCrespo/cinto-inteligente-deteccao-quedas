"""
app.py - Painel web (Streamlit) do monitor OQPNB.

Mesma lógica da interface.py (MQTT + detector de queda), mas mostrando
tudo num navegador em vez do terminal.

Requisitos:
    pip install streamlit paho-mqtt pandas

Uso:
    streamlit run app.py
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

from interface import TOPIC_BASE, extrair_sensores

RSSI_WINDOW = 20
HIST_MAX = 300        # pontos de probabilidade guardados por cinto
EVENTOS_MAX = 50


class Conexao:
    """Cliente MQTT em segundo plano + estado compartilhado com a tela."""

    def __init__(self, broker, port, modelo, limiar):
        self.lock = threading.Lock()
        self.estado = {}            # (belt, anchor) -> {"rssi": [...], "last": dict, "t": float}
        self.anchors_status = {}    # anchor -> "online"/"offline"
        self.hist_prob = {}         # belt -> deque[(datetime, prob)]
        self.quedas = deque(maxlen=EVENTOS_MAX)
        self.eventos = deque(maxlen=EVENTOS_MAX)
        self.total = 0
        self.conectado = False
        self.erro = None

        self.detector = None
        if modelo:
            from detector_queda import DetectorQueda
            self.detector = DetectorQueda(modelo, limiar=limiar)

        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"app_{os.getpid()}")
        except AttributeError:
            self.client = mqtt.Client(client_id=f"app_{os.getpid()}")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        try:
            self.client.connect(broker, port, keepalive=30)
            self.client.loop_start()
        except OSError as e:
            self.erro = str(e)

    # ---------------- MQTT ----------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            self.erro = f"Falha ao conectar: {reason_code}"
            return
        self.conectado = True
        self.erro = None
        client.subscribe(f"{TOPIC_BASE}/#", qos=0)

    def _on_disconnect(self, client, userdata, *args):
        self.conectado = False

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        if msg.topic.endswith("/status"):
            anchor = msg.topic.split("/")[-2]
            with self.lock:
                self.anchors_status[anchor] = payload
                self._evento(f"Anchor {anchor}: {payload}")
            return
        try:
            d = json.loads(payload)
        except json.JSONDecodeError:
            return
        if d.get("type") == "feat":
            self._janela(d)
            return

        belt = d.get("belt") or d.get("mac", "?")
        sensores = extrair_sensores(d)
        with self.lock:
            self.total += 1
            e = self.estado.setdefault((belt, d.get("anchor")), {"rssi": [], "last": None, "t": 0})
            if d.get("rssi") is not None:
                e["rssi"] = (e["rssi"] + [d["rssi"]])[-RSSI_WINDOW:]
            e["last"] = sensores
            e["t"] = time.time()

    def _janela(self, d):
        belt = d.get("belt") or d.get("mac", "?")
        with self.lock:
            self.total += 1
            e = self.estado.setdefault((belt, d.get("anchor")), {"rssi": [], "last": None, "t": 0})
            if d.get("rssi") is not None:
                e["rssi"] = (e["rssi"] + [d["rssi"]])[-RSSI_WINDOW:]
            e["t"] = time.time()
        if self.detector is None:
            return
        j = self.detector.processar(d)
        if j is None:
            return
        agora = datetime.now()
        with self.lock:
            self.hist_prob.setdefault(belt, deque(maxlen=HIST_MAX)).append((agora, j["prob"]))
            if j["queda"]:
                self.quedas.appendleft({
                    "hora": agora.strftime("%H:%M:%S"), "cinto": belt, "anchor": j["anchor"],
                    "prob": round(j["prob"], 2), "amax (g)": j["features"]["amax"],
                    "tilt (graus)": j["features"]["tilt"],
                })
                self._evento(f"QUEDA {belt} prob {j['prob']:.2f} perto da âncora {j['anchor']}")

    def _evento(self, texto):
        self.eventos.appendleft(f"{datetime.now():%H:%M:%S}  {texto}")

    # ---------------- Leitura para a tela ----------------
    def snapshot(self):
        with self.lock:
            agora = time.time()
            linhas = []
            melhores = {}
            for (belt, anchor), e in sorted(self.estado.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
                r = e["rssi"]
                media = sum(r) / len(r) if r else None
                idade = agora - e["t"]
                linhas.append({"cinto": belt, "anchor": anchor,
                               "RSSI atual": r[-1] if r else None,
                               "RSSI médio": round(media, 1) if media is not None else None,
                               "amostras": len(r), "idade (s)": round(idade, 1)})
                if media is not None and idade <= 10 and (belt not in melhores or media > melhores[belt]["rssi"]):
                    melhores[belt] = {"anchor": anchor, "rssi": media, "last": e["last"], "idade": idade}
            hist = {b: list(h) for b, h in self.hist_prob.items()}
            return {
                "tabela": linhas, "melhores": melhores, "hist": hist,
                "quedas": list(self.quedas), "eventos": list(self.eventos),
                "anchors": dict(self.anchors_status), "total": self.total,
                "conectado": self.conectado, "erro": self.erro,
                "perdas": {b: self.detector.taxa_perda(b) for b in self.detector.recebidas} if self.detector else {},
            }

    def fechar(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


@st.cache_resource(show_spinner="Conectando ao broker...")
def conectar(broker, port, modelo, limiar):
    return Conexao(broker, port, modelo, limiar)


# ================= Interface =================
st.set_page_config(page_title="Monitor OQPNB", page_icon="🩺", layout="wide")

with st.sidebar:
    st.header("Conexão")
    broker = st.text_input("Broker MQTT", "localhost")
    port = st.number_input("Porta", 1, 65535, 1883)
    modelo = st.text_input("Modelo de queda (.joblib)", "modelo_queda.joblib")
    usar_modelo = st.checkbox("Ativar detecção de queda", value=os.path.exists(modelo))
    limiar = st.slider("Limiar de alarme (0 = usar o do modelo)", 0.0, 1.0, 0.0, 0.05)
    st.divider()
    auto = st.toggle("Atualizar automaticamente", value=True)
    intervalo = st.slider("Intervalo (s)", 0.5, 5.0, 1.0, 0.5)
    if st.button("Reconectar", use_container_width=True):
        try:
            conectar(broker, int(port), modelo if usar_modelo else None, limiar or None).fechar()
        except Exception:
            pass
        conectar.clear()
        st.rerun()

cx = conectar(broker, int(port), modelo if usar_modelo else None, limiar or None)
s = cx.snapshot()

st.title("Monitor de cintos OQPNB")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Broker", "Conectado" if s["conectado"] else "Desconectado")
c2.metric("Mensagens", s["total"])
c3.metric("Cintos ativos", len(s["melhores"]))
c4.metric("Anchors online", sum(1 for v in s["anchors"].values() if v == "online"))
if s["erro"]:
    st.error(f"Erro MQTT: {s['erro']}")

# -------- alertas de queda --------
if s["quedas"]:
    q = s["quedas"][0]
    st.error(f"**QUEDA DETECTADA** — {q['cinto']} às {q['hora']} "
             f"(prob {q['prob']:.2f}) perto da âncora {q['anchor']}", icon="🚨")

# -------- cartões por cinto --------
st.subheader("Cintos")
if not s["melhores"]:
    st.info("Nenhuma leitura recente. Aguardando dados dos anchors...")
else:
    cols = st.columns(min(len(s["melhores"]), 4))
    for i, (belt, m) in enumerate(sorted(s["melhores"].items(), key=lambda x: str(x[0]))):
        last = m["last"] or {}
        bpm = last.get("bpm")
        prob = s["hist"].get(belt, [(None, None)])[-1][1]
        with cols[i % len(cols)]:
            with st.container(border=True):
                st.markdown(f"### {belt}")
                a, b = st.columns(2)
                a.metric("Anchor mais perto", str(m["anchor"]), f"{m['rssi']:.0f} dBm", delta_color="off")
                b.metric("BPM", f"{bpm:.0f}" if bpm is not None else "--")
                if prob is not None:
                    st.progress(min(max(prob, 0.0), 1.0), text=f"Prob. queda: {prob:.2f}")
                avisos = []
                if last.get("leads_off"):
                    avisos.append("Eletrodos soltos")
                if last.get("mpu_error"):
                    avisos.append("Erro no MPU")
                if belt in s["perdas"] and s["perdas"][belt] > 0.2:
                    avisos.append(f"{100 * s['perdas'][belt]:.0f}% das janelas perdidas")
                for av in avisos:
                    st.warning(av)
                st.caption(f"última leitura há {m['idade']:.1f} s")

# -------- gráfico de probabilidade --------
if s["hist"]:
    st.subheader("Probabilidade de queda")
    series = {}
    for belt, pontos in s["hist"].items():
        series[str(belt)] = pd.Series([p for _, p in pontos], index=[t for t, _ in pontos])
    st.line_chart(pd.DataFrame(series), height=250)

# -------- tabelas --------
t1, t2 = st.columns([3, 2])
with t1:
    st.subheader("RSSI por cinto × anchor")
    if s["tabela"]:
        st.dataframe(pd.DataFrame(s["tabela"]), use_container_width=True, hide_index=True)
    else:
        st.caption("Sem dados.")
with t2:
    st.subheader("Quedas")
    if s["quedas"]:
        st.dataframe(pd.DataFrame(s["quedas"]), use_container_width=True, hide_index=True)
    else:
        st.caption("Nenhuma queda detectada.")

with st.expander("Status dos anchors e eventos"):
    if s["anchors"]:
        st.write({k: v for k, v in sorted(s["anchors"].items())})
    st.text("\n".join(s["eventos"]) or "Sem eventos.")

if auto:
    time.sleep(intervalo)
    st.rerun()
