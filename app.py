"""
app.py - Painel web (Streamlit) do monitor OQPNB MVP.

Mesma lógica da interface_mvp_2.py (pacote texto da antena + DetectorQuedaStream),
mas mostrando tudo num navegador em vez do terminal.

Requisitos:
    pip install streamlit paho-mqtt pandas

Uso:
    python -m streamlit run app.py
"""

import os
import threading
import time
from collections import deque
from datetime import datetime

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

from interface_mvp_2 import TOPIC_BASE, parse_pacote_mvp

RSSI_WINDOW = 20
SINAL_MAX = 500       # amostras guardadas por cinto para os gráficos (5 s a 100 Hz)
HIST_MAX = 300        # pontos de probabilidade por cinto
EVENTOS_MAX = 50
FAIXAS = {"±8 g / ±2000 °/s (cinto_mvp_v2)": ("modelo_mvp_8g.joblib", 4096.0),
          "±2 g / ±250 °/s (cinto_mvp_v1)": ("modelo_mvp_2g.joblib", 16384.0)}


class Conexao:
    """Cliente MQTT em segundo plano + estado compartilhado com a tela."""

    def __init__(self, broker, port, modelo, limiar, lsb_g):
        self.lock = threading.Lock()
        self.lsb_g = lsb_g
        self.estado = {}            # (cinto, antena) -> {"rssi": [...], "last": dict, "t": float}
        self.anchors_status = {}    # antena -> "online"/"offline"
        self.sinal = {}             # cinto -> deque[(datetime, |a| g, ecg)]
        self.hist_prob = {}         # cinto -> deque[(datetime, prob)]
        self.taxa = {}              # cinto -> {"n": int, "t0": float, "hz": float}
        self.quedas = deque(maxlen=EVENTOS_MAX)
        self.eventos = deque(maxlen=EVENTOS_MAX)
        self.total = 0
        self.invalidos = 0
        self.conectado = False
        self.erro = None

        self.detector = None
        if modelo:
            from detector_queda import DetectorQuedaStream
            self.detector = DetectorQuedaStream(modelo, limiar=limiar)

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
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        if msg.topic.endswith("/status"):
            antena = msg.topic.split("/")[-2]
            with self.lock:
                self.anchors_status[antena] = payload
                self._evento(f"Antena {antena}: {payload}")
            return

        d = parse_pacote_mvp(payload)
        if d is None:
            with self.lock:
                self.invalidos += 1
                if self.invalidos <= 5:
                    self._evento(f"Pacote inválido em {msg.topic}: {payload[:60]}")
            return

        agora = datetime.now()
        t = time.time()
        cinto, antena = d["id_cinto"], d["id_antena"]
        amag = (d["ax"] ** 2 + d["ay"] ** 2 + d["az"] ** 2) ** 0.5 / self.lsb_g
        with self.lock:
            self.total += 1
            e = self.estado.setdefault((cinto, antena), {"rssi": [], "last": None, "t": 0})
            e["rssi"] = (e["rssi"] + [d["rssi"]])[-RSSI_WINDOW:]
            e["last"] = d
            e["t"] = t
            self.sinal.setdefault(cinto, deque(maxlen=SINAL_MAX)).append((agora, amag, d["sinal_ad8232"]))
            tx = self.taxa.setdefault(cinto, {"n": 0, "t0": t, "hz": 0.0})
            tx["n"] += 1
            if t - tx["t0"] >= 1.0:
                tx["hz"] = tx["n"] / (t - tx["t0"])
                tx["n"], tx["t0"] = 0, t

        if self.detector is None:
            return
        raw = (d["ax"], d["ay"], d["az"], d["gx"], d["gy"], d["gz"])
        j = self.detector.adicionar(cinto, antena, d["rssi"], raw, seq=d["seq"], agora=t)
        if j is None:
            return
        with self.lock:
            self.hist_prob.setdefault(cinto, deque(maxlen=HIST_MAX)).append((agora, j["prob"]))
            if j["queda"]:
                self.quedas.appendleft({
                    "hora": agora.strftime("%H:%M:%S"), "cinto": cinto, "antena": j["anchor"],
                    "prob": round(j["prob"], 2), "amax (g)": j["features"]["amax"],
                    "tilt (graus)": j["features"]["tilt"],
                })
                self._evento(f"QUEDA cinto {cinto} prob {j['prob']:.2f} perto da antena {j['anchor']}")

    def _evento(self, texto):
        self.eventos.appendleft(f"{datetime.now():%H:%M:%S}  {texto}")

    # ---------------- Leitura para a tela ----------------
    def snapshot(self):
        with self.lock:
            agora = time.time()
            linhas = []
            melhores = {}
            for (cinto, antena), e in sorted(self.estado.items()):
                r = e["rssi"]
                media = sum(r) / len(r) if r else None
                idade = agora - e["t"]
                linhas.append({"cinto": cinto, "antena": antena,
                               "RSSI atual": r[-1] if r else None,
                               "RSSI médio": round(media, 1) if media is not None else None,
                               "amostras": len(r), "idade (s)": round(idade, 1)})
                if media is not None and idade <= 10 and (cinto not in melhores or media > melhores[cinto]["rssi"]):
                    melhores[cinto] = {"antena": antena, "rssi": media, "last": e["last"], "idade": idade}
            det = self.detector
            return {
                "tabela": linhas, "melhores": melhores,
                "sinal": {c: list(s) for c, s in self.sinal.items()},
                "hist": {c: list(h) for c, h in self.hist_prob.items()},
                "taxa": {c: tx["hz"] for c, tx in self.taxa.items()},
                "quedas": list(self.quedas), "eventos": list(self.eventos),
                "anchors": dict(self.anchors_status), "total": self.total, "invalidos": self.invalidos,
                "conectado": self.conectado, "erro": self.erro,
                "perdas": {c: det.taxa_perda(c) for c in det.amostras} if det else {},
                "resets": dict(det.resets) if det else {},
            }

    def fechar(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


@st.cache_resource(show_spinner="Conectando ao broker...")
def conectar(broker, port, modelo, limiar, lsb_g):
    return Conexao(broker, port, modelo, limiar, lsb_g)


# ================= Interface =================
st.set_page_config(page_title="Monitor OQPNB", page_icon="🩺", layout="wide")

with st.sidebar:
    st.header("Conexão")
    broker = st.text_input("Broker MQTT", "localhost")
    port = st.number_input("Porta", 1, 65535, 1883)
    faixa = st.radio("Faixa do MPU no cinto", list(FAIXAS), index=0)
    modelo_padrao, lsb_g = FAIXAS[faixa]
    modelo = st.text_input("Modelo de queda (.joblib)", modelo_padrao)
    usar_modelo = st.checkbox("Ativar detecção de queda", value=os.path.exists(modelo))
    limiar = st.slider("Limiar de alarme (0 = usar o do modelo)", 0.0, 1.0, 0.0, 0.05)
    st.divider()
    auto = st.toggle("Atualizar automaticamente", value=True)
    intervalo = st.slider("Intervalo (s)", 0.5, 5.0, 1.0, 0.5)
    params = (broker, int(port), modelo if usar_modelo else None, limiar or None, lsb_g)
    if st.button("Reconectar", use_container_width=True):
        try:
            conectar(*params).fechar()
        except Exception:
            pass
        conectar.clear()
        st.rerun()

cx = conectar(*params)
s = cx.snapshot()

st.title("Monitor de cintos OQPNB")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Broker", "Conectado" if s["conectado"] else "Desconectado")
c2.metric("Amostras recebidas", s["total"])
c3.metric("Cintos ativos", len(s["melhores"]))
c4.metric("Antenas online", sum(1 for v in s["anchors"].values() if v == "online"))
if s["erro"]:
    st.error(f"Erro MQTT: {s['erro']}")
if s["invalidos"]:
    st.warning(f"{s['invalidos']} pacotes com formato inválido (veja os eventos abaixo).")

# -------- alertas de queda --------
if s["quedas"]:
    q = s["quedas"][0]
    st.error(f"**QUEDA DETECTADA** — cinto {q['cinto']} às {q['hora']} "
             f"(prob {q['prob']:.2f}) perto da antena {q['antena']}", icon="🚨")

# -------- cartões por cinto --------
st.subheader("Cintos")
if not s["melhores"]:
    if s["anchors"] and not s["total"]:
        st.info("Antena online, mas nenhum pacote de cinto chegou ainda. "
                "Verifique no Serial da antena se ela mostra 'GATT: CONECTADO' e 'TX MQTT' > 0.")
    else:
        st.info("Nenhuma leitura recente. Aguardando dados das antenas...")
else:
    cols = st.columns(min(len(s["melhores"]), 4))
    for i, (cinto, m) in enumerate(sorted(s["melhores"].items())):
        last = m["last"] or {}
        prob = s["hist"].get(cinto, [(None, None)])[-1][1]
        with cols[i % len(cols)]:
            with st.container(border=True):
                st.markdown(f"### Cinto {cinto}")
                a, b = st.columns(2)
                a.metric("Antena mais perto", str(m["antena"]), f"{m['rssi']:.0f} dBm", delta_color="off")
                b.metric("Taxa", f"{s['taxa'].get(cinto, 0):.0f} Hz")
                if prob is not None:
                    st.progress(min(max(prob, 0.0), 1.0), text=f"Prob. queda: {prob:.2f}")
                if last.get("eletrodos_conectados") == 0:
                    st.warning("Eletrodos soltos")
                else:
                    st.caption(f"ECG (AD8232): {last.get('sinal_ad8232')}")
                if s["perdas"].get(cinto, 0) > 0.05:
                    st.warning(f"{100 * s['perdas'][cinto]:.0f}% das amostras perdidas")
                if s["resets"].get(cinto):
                    st.caption(f"janela reiniciada {s['resets'][cinto]}x por buraco nos dados")
                st.caption(f"última leitura há {m['idade']:.1f} s")

# -------- gráficos --------
if s["sinal"]:
    g1, g2 = st.columns(2)
    with g1:
        st.subheader("|a| (g) — últimos 5 s")
        df = pd.DataFrame({f"cinto {c}": pd.Series([a for _, a, _ in p], index=[t for t, _, _ in p])
                           for c, p in s["sinal"].items()})
        st.line_chart(df, height=220)
    with g2:
        st.subheader("ECG bruto (AD8232)")
        df = pd.DataFrame({f"cinto {c}": pd.Series([e for _, _, e in p], index=[t for t, _, _ in p])
                           for c, p in s["sinal"].items()})
        st.line_chart(df, height=220)

if s["hist"]:
    st.subheader("Probabilidade de queda")
    df = pd.DataFrame({f"cinto {c}": pd.Series([p for _, p in h], index=[t for t, _ in h])
                       for c, h in s["hist"].items()})
    st.line_chart(df, height=220)

# -------- tabelas --------
t1, t2 = st.columns([3, 2])
with t1:
    st.subheader("RSSI por cinto × antena")
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

with st.expander("Status das antenas e eventos"):
    if s["anchors"]:
        st.write({k: v for k, v in sorted(s["anchors"].items())})
    st.text("\n".join(s["eventos"]) or "Sem eventos.")

if auto:
    time.sleep(intervalo)
    st.rerun()
