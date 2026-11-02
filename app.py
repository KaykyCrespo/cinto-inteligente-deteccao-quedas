"""
app.py - Painel web (Streamlit) do monitor OQPNB MVP.

Mesma lógica da interface_mvp_2.py (pacote texto da antena + DetectorQuedaStream),
mas mostrando tudo num navegador em vez do terminal.

Requisitos:
    pip install streamlit paho-mqtt pandas

Uso:
    python -m streamlit run app.py

O cinto (cinto_mvp_v1) manda os valores crus do MPU6050 em ±8 g / ±2000 °/s,
e a detecção usa o modelo_mvp_8g.joblib (treinado no SisFall com essas faixas).

Gravação e download de CSV (barra lateral):
  - "Gravar amostras" salva cada amostra em gravacoes/amostras_<data>.csv e cada
    janela analisada em gravacoes/janelas_<data>.csv, com a anotação atual.
  - A seção "Baixar CSV" no fim da página baixa as janelas, as quedas e a última
    gravação de amostras.
"""

import csv
import io
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

from interface_mvp_2 import TOPIC_BASE, parse_pacote_mvp

BROKER = os.environ.get("OQPNB_BROKER", "localhost")
PORT = int(os.environ.get("OQPNB_PORT", "1883"))
MODELO = os.environ.get("OQPNB_MODELO", "modelo_mvp_8g.joblib")
LSB_G_PADRAO = 4096.0     # ±8 g (só usado se a detecção estiver desligada)
PASTA_GRAVACOES = "gravacoes"
JANELAS_MAX = 20000       # janelas guardadas em memória para download (~3 h)
RSSI_WINDOW = 20
SINAL_MAX = 500       # amostras guardadas por cinto para os gráficos (5 s a 100 Hz)
HIST_MAX = 300        # pontos de probabilidade por cinto
EVENTOS_MAX = 50
AMOSTRA_COLS = ["timestamp", "id_cinto", "id_antena", "rssi", "seq", "ax", "ay", "az",
                "gx", "gy", "gz", "eletrodos_conectados", "sinal_ad8232", "anotacao"]
JANELA_COLS = ["timestamp", "id_cinto", "id_antena", "prob", "queda",
               "amax", "amin", "astd", "gmax", "gstd", "tilt", "jerk", "post_std", "anotacao"]


class Conexao:
    """Cliente MQTT em segundo plano + estado compartilhado com a tela."""

    def __init__(self, broker, port, detectar, limiar):
        self.lock = threading.Lock()
        self.detectar = detectar
        self.limiar = limiar
        self.lsb_g = LSB_G_PADRAO
        self.faixa = None
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
        if detectar:
            if os.path.exists(MODELO):
                from detector_queda import DetectorQuedaStream
                self.detector = DetectorQuedaStream(MODELO, limiar=limiar)
                d = self.detector
                self.lsb_g = d.lsb_g
                self.faixa = f"{d.fs} Hz, ±{d.faixa_acc:g} g / ±{d.faixa_giro:g} °/s"
                self._evento(f"Modelo {MODELO} carregado ({self.faixa}, limiar {d.limiar:.2f})")
            else:
                self.erro = f"Modelo {MODELO} não encontrado; detecção desligada"

        # gravação / download
        self.janelas = deque(maxlen=JANELAS_MAX)
        self.anotacao = ""
        self.grav = None            # {"amostras": (arquivo, writer), "janelas": (...), "n": int, ...}
        self.ultima_gravacao = None # caminhos da última gravação encerrada

        # id único: dois clientes com o mesmo id se derrubam mutuamente no broker
        cid = f"app_{uuid.uuid4().hex[:8]}"
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
        except AttributeError:
            self.client = mqtt.Client(client_id=cid)
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

    # ---------------- Gravação em CSV ----------------
    def iniciar_gravacao(self):
        with self.lock:
            if self.grav:
                return
            os.makedirs(PASTA_GRAVACOES, exist_ok=True)
            tag = datetime.now().strftime("%Y%m%d_%H%M%S")
            g = {"inicio": datetime.now(), "n": 0}
            for nome, cols in (("amostras", AMOSTRA_COLS), ("janelas", JANELA_COLS)):
                caminho = os.path.join(PASTA_GRAVACOES, f"{nome}_{tag}.csv")
                f = open(caminho, "w", newline="", encoding="utf-8")
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                g[nome] = (f, w, caminho)
            self.grav = g
            self._evento(f"Gravação iniciada: {g['amostras'][2]}")

    def parar_gravacao(self):
        with self.lock:
            g, self.grav = self.grav, None
            if not g:
                return
            for nome in ("amostras", "janelas"):
                g[nome][0].close()
            self.ultima_gravacao = {"amostras": g["amostras"][2], "janelas": g["janelas"][2], "n": g["n"]}
            self._evento(f"Gravação encerrada: {g['n']} amostras em {g['amostras'][2]}")

    def status_gravacao(self):
        with self.lock:
            if self.grav:
                return {"ativa": True, "n": self.grav["n"], "arquivo": self.grav["amostras"][2],
                        "seg": (datetime.now() - self.grav["inicio"]).total_seconds()}
            return {"ativa": False, "ultima": self.ultima_gravacao}

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
        with self.lock:
            if self.grav:
                f, w, _ = self.grav["amostras"]
                w.writerow({"timestamp": agora.isoformat(timespec="milliseconds"), **d,
                            "anotacao": self.anotacao})
                self.grav["n"] += 1
                if self.grav["n"] % 200 == 0:
                    f.flush()
            amag = (d["ax"] ** 2 + d["ay"] ** 2 + d["az"] ** 2) ** 0.5 / self.lsb_g
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
            linha = {"timestamp": agora.isoformat(timespec="milliseconds"), "id_cinto": cinto,
                     "id_antena": j["anchor"], "prob": round(j["prob"], 4), "queda": j["queda"],
                     **j["features"], "anotacao": self.anotacao}
            self.janelas.append(linha)
            if self.grav:
                f, w, _ = self.grav["janelas"]
                w.writerow(linha)
                f.flush()
            self.hist_prob.setdefault(cinto, deque(maxlen=HIST_MAX)).append((agora, j["prob"]))
            if j["queda"]:
                self.quedas.appendleft({
                    "data": agora.strftime("%Y-%m-%d"),
                    "hora": agora.strftime("%H:%M:%S"), "cinto": cinto, "antena": j["anchor"],
                    "prob": round(j["prob"], 2), "amax (g)": j["features"]["amax"],
                    "tilt (graus)": j["features"]["tilt"], "anotacao": self.anotacao,
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
                "conectado": self.conectado, "erro": self.erro, "faixa": self.faixa,
                "perdas": {c: det.taxa_perda(c) for c in det.amostras} if det else {},
                "resets": dict(det.resets) if det else {},
                "n_janelas": len(self.janelas),
            }

    def janelas_csv(self):
        with self.lock:
            linhas = list(self.janelas)
        return _para_csv(linhas, JANELA_COLS)

    def fechar(self):
        self.parar_gravacao()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


def _para_csv(linhas, colunas):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colunas, extrasaction="ignore")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue().encode("utf-8-sig")   # utf-8-sig: o Excel abre com acentos certos


@st.cache_data(max_entries=4, show_spinner=False)
def _ler_arquivo(caminho, mtime, tamanho):
    """Lê o CSV gravado uma vez só (o cache muda quando o arquivo muda)."""
    with open(caminho, "rb") as f:
        return f.read()


@st.cache_resource
def _holder():
    return {}


def conectar(*params):
    """Mantém uma única conexão MQTT viva; recria só se os parâmetros mudarem."""
    h = _holder()
    if h.get("params") != params:
        if "cx" in h:
            h["cx"].fechar()
        with st.spinner("Conectando ao broker..."):
            h["cx"] = Conexao(*params)
        h["params"] = params
    return h["cx"]


# ================= Interface =================
st.set_page_config(page_title="Monitor OQPNB", page_icon="🩺", layout="wide")

with st.sidebar:
    st.header("Detecção")
    detectar = st.checkbox("Ativar detecção de queda", value=True)
    limiar = st.slider("Limiar de alarme (0 = usar o do modelo)", 0.0, 1.0, 0.0, 0.05)
    st.divider()
    st.header("Gravação")
    anotacao = st.text_input("Anotação (o que está acontecendo agora)",
                             placeholder="ex.: queda frente 1, sentar rápido, andando",
                             help="Vai junto em cada linha gravada. Útil para calcular acertos depois.")
    st.divider()
    st.header("Tela")
    auto = st.toggle("Atualizar automaticamente", value=True)
    intervalo = st.slider("Intervalo (s)", 0.5, 5.0, 1.0, 0.5)
    st.divider()
    params = (BROKER, PORT, detectar, limiar or None)
    if st.button("Reconectar", use_container_width=True):
        h = _holder()
        if "cx" in h:
            h["cx"].fechar()
        h.clear()
        st.rerun()
    st.caption(f"Broker: {BROKER}:{PORT}")

cx = conectar(*params)
cx.anotacao = anotacao.strip()

with st.sidebar:
    g = cx.status_gravacao()
    if g["ativa"]:
        st.success(f"Gravando: {g['n']} amostras ({g['seg']:.0f} s)")
        if st.button("Parar gravação", use_container_width=True, type="primary"):
            cx.parar_gravacao()
            st.rerun()
    else:
        if st.button("Gravar amostras", use_container_width=True):
            cx.iniciar_gravacao()
            st.rerun()

s = cx.snapshot()

st.title("Monitor de cintos OQPNB")
if s["faixa"]:
    st.caption(f"Cinto detectado: {s['faixa']}")

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

# -------- downloads --------
st.subheader("Baixar CSV")
d1, d2, d3 = st.columns(3)
tag = datetime.now().strftime("%Y%m%d_%H%M%S")
with d1:
    st.download_button(f"Janelas analisadas ({s['n_janelas']})", cx.janelas_csv(),
                       file_name=f"janelas_{tag}.csv", mime="text/csv",
                       disabled=not s["n_janelas"], use_container_width=True)
with d2:
    cols_q = ["data", "hora", "cinto", "antena", "prob", "amax (g)", "tilt (graus)", "anotacao"]
    st.download_button(f"Quedas detectadas ({len(s['quedas'])})", _para_csv(s["quedas"], cols_q),
                       file_name=f"quedas_{tag}.csv", mime="text/csv",
                       disabled=not s["quedas"], use_container_width=True)
with d3:
    g = cx.status_gravacao()
    if g["ativa"]:
        st.button("Amostras: pare a gravação para baixar", disabled=True, use_container_width=True)
    elif g["ultima"] and os.path.exists(g["ultima"]["amostras"]):
        caminho = g["ultima"]["amostras"]
        st_ = os.stat(caminho)
        st.download_button(f"Amostras da última gravação ({g['ultima']['n']})",
                           _ler_arquivo(caminho, st_.st_mtime, st_.st_size),
                           file_name=os.path.basename(caminho), mime="text/csv",
                           use_container_width=True)
    else:
        st.button("Amostras: use 'Gravar amostras' na barra lateral", disabled=True,
                  use_container_width=True)
st.caption(f"As gravações ficam também na pasta {os.path.abspath(PASTA_GRAVACOES)}")

if auto:
    time.sleep(intervalo)
    st.rerun()
