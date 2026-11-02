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
    janela analisada em gravacoes/janelas_<data>.csv.
  - A seção "Baixar CSV" no fim da página baixa as janelas, as quedas e a última
    gravação de amostras.
"""

import csv
import hashlib
import io
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime

import altair as alt
import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

from interface_mvp_2 import TOPIC_BASE, parse_pacote_mvp

BROKER = os.environ.get("OQPNB_BROKER", "localhost")
PORT = int(os.environ.get("OQPNB_PORT", "1883"))
MODELO = os.environ.get("OQPNB_MODELO", "modelo_mvp_8g.joblib")
LSB_G_PADRAO = 4096.0     # ±8 g (só usado se a detecção estiver desligada)
LSB_DPS_PADRAO = 16.4     # ±2000 °/s (idem)
PASTA_GRAVACOES = "gravacoes"
ROTACAO_MIN = 60          # fecha o CSV de amostras e abre a próxima parte a cada N minutos
JANELAS_MAX = 20000       # janelas guardadas em memória para download (~3 h)
RSSI_WINDOW = 20
SINAL_MAX = 500       # amostras guardadas por cinto para os gráficos (5 s a 100 Hz)
HIST_MAX = 300        # pontos de probabilidade por cinto
EVENTOS_MAX = 50
AMOSTRA_COLS = ["timestamp", "id_cinto", "id_antena", "rssi", "seq", "ax", "ay", "az",
                "gx", "gy", "gz", "eletrodos_conectados", "sinal_ad8232"]
JANELA_COLS = ["timestamp", "id_cinto", "id_antena", "prob", "queda",
               "amax", "amin", "astd", "gmax", "gstd", "tilt", "jerk", "post_std"]


class Conexao:
    """Cliente MQTT em segundo plano + estado compartilhado com a tela."""

    def __init__(self, broker, port, detectar, limiar):
        self.lock = threading.Lock()
        self.detectar = detectar
        self.limiar = limiar
        self.lsb_g = LSB_G_PADRAO
        self.lsb_dps = LSB_DPS_PADRAO
        self.faixa = None
        self.estado = {}            # (cinto, antena) -> {"rssi": [...], "t": float, "gatt": bool}
        self.ultima = {}            # cinto -> última leitura de sensores (só de pacotes GATT)
        self.anchors_status = {}    # antena -> "online"/"offline"
        self.sinal = {}             # cinto -> deque[(datetime, |a| g, |w| °/s, ecg)]
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
                self.lsb_dps = d.lsb_dps
                self.faixa = f"{d.fs} Hz, ±{d.faixa_acc:g} g / ±{d.faixa_giro:g} °/s"
                self._evento(f"Modelo {MODELO} carregado ({self.faixa}, limiar {d.limiar:.2f})")
            else:
                self.erro = f"Modelo {MODELO} não encontrado; detecção desligada"

        # gravação / download
        self.janelas = deque(maxlen=JANELAS_MAX)
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
    def _abrir_csv(self, nome, cols, parte=None):
        sufixo = f"_p{parte:02d}" if parte else ""
        caminho = os.path.join(PASTA_GRAVACOES, f"{nome}_{self.grav['tag']}{sufixo}.csv")
        f = open(caminho, "w", newline="", encoding="utf-8")
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        return (f, w, caminho)

    def iniciar_gravacao(self):
        with self.lock:
            if self.grav:
                return
            os.makedirs(PASTA_GRAVACOES, exist_ok=True)
            agora = datetime.now()
            self.grav = {"inicio": agora, "inicio_parte": agora, "n": 0, "n_parte": 0,
                         "parte": 1, "partes": [], "tag": agora.strftime("%Y%m%d_%H%M%S")}
            self.grav["amostras"] = self._abrir_csv("amostras", AMOSTRA_COLS, parte=1)
            self.grav["janelas"] = self._abrir_csv("janelas", JANELA_COLS)
            self._evento(f"Gravação iniciada: {self.grav['amostras'][2]}")

    def _rotacionar_se_preciso(self, agora):
        """Chamado com o lock: fecha a parte atual de amostras e abre a próxima após ROTACAO_MIN."""
        g = self.grav
        if (agora - g["inicio_parte"]).total_seconds() < ROTACAO_MIN * 60:
            return
        f, _, caminho = g["amostras"]
        f.close()
        g["partes"].append({"caminho": caminho, "n": g["n_parte"]})
        g["parte"] += 1
        g["n_parte"] = 0
        g["inicio_parte"] = agora
        g["amostras"] = self._abrir_csv("amostras", AMOSTRA_COLS, parte=g["parte"])
        self._evento(f"Gravação: parte {g['parte']} iniciada ({os.path.basename(g['amostras'][2])})")

    def parar_gravacao(self):
        with self.lock:
            g, self.grav = self.grav, None
            if not g:
                return
            for nome in ("amostras", "janelas"):
                g[nome][0].close()
            g["partes"].append({"caminho": g["amostras"][2], "n": g["n_parte"]})
            self.ultima_gravacao = {"amostras": g["amostras"][2], "partes": g["partes"],
                                    "janelas": g["janelas"][2], "n": g["n"]}
            self._evento(f"Gravação encerrada: {g['n']} amostras em {len(g['partes'])} parte(s)")

    def status_gravacao(self):
        with self.lock:
            if self.grav:
                return {"ativa": True, "n": self.grav["n"], "arquivo": self.grav["amostras"][2],
                        "parte": self.grav["parte"],
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
        somente_rssi = d.pop("somente_rssi")
        with self.lock:
            if self.grav:
                self._rotacionar_se_preciso(agora)
                f, w, _ = self.grav["amostras"]
                w.writerow({"timestamp": agora.isoformat(timespec="milliseconds"), **d})
                self.grav["n"] += 1
                self.grav["n_parte"] += 1
                if self.grav["n_parte"] % 200 == 0:
                    f.flush()
            e = self.estado.setdefault((cinto, antena), {"rssi": [], "t": 0, "gatt": False})
            e["rssi"] = (e["rssi"] + [d["rssi"]])[-RSSI_WINDOW:]
            e["t"] = t
            e["gatt"] = not somente_rssi

        # antena sem GATT: só RSSI do anúncio -> entra na localização, não nos sinais
        if somente_rssi:
            if self.detector is not None:
                self.detector.atualizar_rssi(cinto, antena, d["rssi"])
            return

        amag = (d["ax"] ** 2 + d["ay"] ** 2 + d["az"] ** 2) ** 0.5 / self.lsb_g
        gmag = (d["gx"] ** 2 + d["gy"] ** 2 + d["gz"] ** 2) ** 0.5 / self.lsb_dps
        with self.lock:
            self.total += 1
            self.ultima[cinto] = d
            self.sinal.setdefault(cinto, deque(maxlen=SINAL_MAX)).append((agora, amag, gmag, d["sinal_ad8232"]))
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
                     **j["features"]}
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
                               "origem": "GATT" if e["gatt"] else "anúncio",
                               "amostras": len(r), "idade (s)": round(idade, 1)})
                if media is not None and idade <= 10 and (cinto not in melhores or media > melhores[cinto]["rssi"]):
                    melhores[cinto] = {"antena": antena, "rssi": media, "last": self.ultima.get(cinto),
                                       "idade": idade, "gatt": e["gatt"]}
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


# muda só quando o arquivo é salvo (hot reload), não a cada rerun
with open(__file__, "rb") as _f:
    _VERSAO_CONEXAO = hashlib.md5(_f.read()).hexdigest()


def conectar(*params):
    """Mantém uma única conexão MQTT viva; recria se os parâmetros ou o código mudarem."""
    h = _holder()
    if h.get("params") != params or h.get("versao") != _VERSAO_CONEXAO:
        if "cx" in h:
            h["cx"].fechar()
        with st.spinner("Conectando ao broker..."):
            h["cx"] = Conexao(*params)
        h["params"] = params
        h["versao"] = _VERSAO_CONEXAO
    return h["cx"]


def nome_cinto(cinto):
    try:
        return f"OQPNB{int(cinto):02d}"
    except (TypeError, ValueError):
        return str(cinto)


# ================= Interface =================
st.set_page_config(page_title="Monitor OQPNB", page_icon="🩺", layout="wide")

with st.sidebar:
    st.header("Detecção")
    detectar = st.checkbox("Ativar detecção de queda", value=True)
    limiar = st.slider("Limiar de alarme (0 = usar o do modelo)", 0.0, 1.0, 0.0, 0.05)
    st.divider()
    st.header("Gravação")
    gravacao_box = st.container()     # preenchido depois que a conexão existir
    st.divider()
    st.header("Tela")
    auto = st.toggle("Atualizar automaticamente", value=True)
    intervalo = st.slider("Intervalo (s)", 0.5, 5.0, 1.0, 0.5)
    st.divider()
    params = (BROKER, PORT, detectar, limiar or None)
    if st.button("Reconectar", width="stretch"):
        h = _holder()
        if "cx" in h:
            h["cx"].fechar()
        h.clear()
        st.rerun()

cx = conectar(*params)

with gravacao_box:
    g = cx.status_gravacao()
    if g["ativa"]:
        st.success(f"Gravando: {g['n']} amostras ({g['seg'] / 60:.0f} min) — parte {g['parte']}")
        if st.button("Parar gravação", width="stretch", type="primary"):
            cx.parar_gravacao()
            st.rerun()
    else:
        if st.button("Gravar amostras", width="stretch"):
            cx.iniciar_gravacao()
            st.rerun()

s = cx.snapshot()

monitor_tab, detalhes_tab = st.tabs(["Monitoramento", "Detalhes técnicos"])

with monitor_tab:
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
        st.error(f"**QUEDA DETECTADA** — cinto {nome_cinto(q['cinto'])} às {q['hora']} "
                 f"(prob {q['prob']:.2f}) perto da antena {q['antena']}", icon="🚨")

    # -------- cartões por cinto --------
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
                    nome_exibicao = nome_cinto(cinto)
                    st.markdown(f"### CINTO {nome_exibicao}")
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
                        st.caption(f"Janela reiniciada {s['resets'][cinto]}x por buraco nos dados | Última leitura há {m['idade']:.1f}s")
                    else:
                        st.caption(f"Última leitura há {m['idade']:.1f}s")

    st.subheader("Probabilidade de queda")
    N_PROB = 10
    if s["hist"]:
        linhas = []
        rotulos = {}        # pos -> hh:mm:ss (do cinto com a janela mais recente)
        ref = max(s["hist"].items(), key=lambda kv: kv[1][-1][0] if kv[1] else datetime.min)[0]
        for c, h in s["hist"].items():
            ultimos = list(h)[-N_PROB:]
            # posição fixa: 0 = janela mais recente, -1 = anterior, ... (eixo não depende do horário)
            for pos, (t, p) in zip(range(-(len(ultimos) - 1), 1), ultimos):
                dt = pd.to_datetime(t)
                if c == ref:
                    rotulos[pos] = dt.strftime("%H:%M:%S")
                linhas.append({
                    "pos": pos,
                    "cinto": nome_cinto(c),
                    "probabilidade": float(p),
                    "horario_label": dt.strftime("%H:%M:%S"),
                    "data_label": dt.strftime("%d %b %Y").upper(),
                })

        if linhas:
            df = pd.DataFrame(linhas)
            # expressão Vega: troca o número da posição pelo horário da janela
            mapa = ", ".join(f"'{pos}': '{rotulos.get(pos, '')}'" for pos in range(-(N_PROB - 1), 1))
            label_expr = "{" + mapa + "}[toString(datum.value)]"
            # uma escala de cor única para cintos + limiar, para o limiar aparecer na legenda
            cintos = sorted(df["cinto"].unique())
            paleta = ["#4c78a8", "#f58518", "#54a24b", "#72b7b2", "#b279a2", "#eeca3b", "#9d755d", "#bab0ac"]
            dominio, cores = list(cintos), paleta[:len(cintos)]
            if cx.detector is not None:
                rotulo_limiar = f"Limiar de alerta ({cx.detector.limiar:.2f})"
                dominio.append(rotulo_limiar)
                cores.append("red")
            escala_cor = alt.Scale(domain=dominio, range=cores)
            base = alt.Chart(df).encode(
                x=alt.X("pos:Q", title="Horário",
                        scale=alt.Scale(domain=[-(N_PROB - 1), 0], nice=False),
                        axis=alt.Axis(values=list(range(-(N_PROB - 1), 1)), labelExpr=label_expr,
                                      labelAngle=-45, grid=True)),
                y=alt.Y("probabilidade:Q", title="Probabilidade",
                        scale=alt.Scale(domain=[0, 1], nice=False)),
                color=alt.Color("cinto:N", title="Legenda", scale=escala_cor),
                tooltip=[
                    alt.Tooltip("horario_label:N", title="Horário"),
                    alt.Tooltip("data_label:N", title="Data"),
                    alt.Tooltip("cinto:N", title="Cinto"),
                    alt.Tooltip("probabilidade:Q", title="Probabilidade", format=".2f"),
                ],
            )
            chart = base.mark_line() + base.mark_point(filled=True, size=60)
            if cx.detector is not None:
                limiar_df = pd.DataFrame({"y": [cx.detector.limiar], "cinto": [rotulo_limiar]})
                chart += alt.Chart(limiar_df).mark_rule(strokeDash=[6, 4], strokeWidth=2).encode(
                    y="y:Q", color=alt.Color("cinto:N", title="Legenda", scale=escala_cor),
                    tooltip=[alt.Tooltip("y:Q", title="Limiar", format=".2f")])
            st.altair_chart(chart.properties(height=260), width="stretch")
        else:
            st.caption("Nenhuma probabilidade de queda registrada.")

    # -------- quedas detectadas --------
    st.subheader("Quedas detectadas")
    if s["quedas"]:
        st.dataframe(pd.DataFrame(s["quedas"]), width="stretch", hide_index=True)
    else:
        st.caption("Nenhuma queda detectada.")

with detalhes_tab:
    col1, col2, col3 = st.columns(3)
    col1.metric("Broker", "Conectado" if s["conectado"] else "Desconectado")
    col2.metric("Pacotes inválidos", s["invalidos"])
    if cx.detector is not None:
        col3.metric("Modelo", os.path.basename(MODELO), f"limiar {cx.detector.limiar:.2f}", delta_color="off")
        col3.caption(s["faixa"])
    else:
        col3.metric("Modelo", "desligado")
        col3.caption(os.path.basename(MODELO) if os.path.exists(MODELO) else f"{MODELO} não encontrado")

    if s["erro"]:
        st.error(f"Erro MQTT: {s['erro']}")

    # métricas internas (uma linha de cards; valores por cinto quando houver vários)
    def _por_cinto(d, fmt):
        if not d:
            return "—"
        if len(d) == 1:
            return fmt(next(iter(d.values())))
        return " | ".join(f"{nome_cinto(k)}: {fmt(v)}" for k, v in sorted(d.items()))

    prob_atual = {k: v[-1][1] for k, v in s["hist"].items() if v}
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Amostras recebidas", s["total"])
    m2.metric("Cintos ativos", len(s["melhores"]))
    m3.metric("Prob. queda atual", _por_cinto(prob_atual, lambda v: f"{v:.2f}"))
    m4.metric("Taxa (Hz)", _por_cinto(s["taxa"], lambda v: f"{v:.0f}"))
    m5.metric("Amostras perdidas", _por_cinto(s["perdas"], lambda v: f"{100 * v:.1f}%"))
    m6.metric("Janelas reiniciadas", _por_cinto(s["resets"], lambda v: f"{v}"))

    st.subheader("Status do sistema")
    col_cinto, col_antenas = st.columns([1, 2])
    ALT_CARD = 190                       # mesma altura para o card do cinto e o das antenas

    with col_cinto:
        cinto_ids = sorted(set(s["melhores"].keys()) | set(s["hist"].keys()) | set(s["sinal"].keys()) | set(s["taxa"].keys()))
        if cinto_ids:
            for cinto in cinto_ids:
                m = s["melhores"].get(cinto)
                last = (m or {}).get("last") or {}
                with st.container(border=True, height=ALT_CARD):
                    if m:
                        st.markdown(f"**CINTO {nome_cinto(cinto)}** :green[● ONLINE]")
                        st.caption(f"Antena mais perto: {m['antena']} ({m['rssi']:.0f} dBm)")
                        st.caption(f"Taxa: {s['taxa'].get(cinto, 0):.0f} Hz | "
                                   f"Eletrodos: {'OK' if last.get('eletrodos_conectados') == 1 else 'soltos'}")
                        st.caption(f"Última leitura há {m['idade']:.1f} s")
                    else:
                        st.markdown(f"**CINTO {nome_cinto(cinto)}** :red[● OFFLINE]")
                        st.caption("Sem leitura nos últimos 10 s")
        else:
            with st.container(border=True, height=ALT_CARD):
                st.markdown("**CINTO —** :orange[● SEM CINTO]")
                st.caption("Nenhum cinto detectado")

    with col_antenas:
        ANTENAS = [1, 2, 3, 4]
        status_antenas = {str(k): v for k, v in s["anchors"].items()}
        # RSSI mais recente visto por cada antena (de qualquer cinto)
        rssi_antena = {}
        for linha in s["tabela"]:
            a = str(linha["antena"])
            if linha["RSSI atual"] is not None and (a not in rssi_antena or linha["idade (s)"] < rssi_antena[a][1]):
                rssi_antena[a] = (linha["RSSI atual"], linha["idade (s)"])
        with st.container(border=True, height=ALT_CARD):
            cols = st.columns(len(ANTENAS))
            for col, antena in zip(cols, ANTENAS):
                status = status_antenas.get(str(antena))
                if status == "online":
                    badge, cor = "ONLINE", "green"
                elif status == "offline":
                    badge, cor = "OFFLINE", "red"
                else:
                    badge, cor = "SEM STATUS", "orange"
                r = rssi_antena.get(str(antena))
                with col:
                    st.markdown(f"**Anchor {antena}**")
                    st.markdown(f":{cor}[● {badge}]")
                    st.metric("RSSI", f"{r[0]} dBm" if r else "—",
                              f"há {r[1]:.0f} s" if r else None, delta_color="off",
                              label_visibility="collapsed")

    st.subheader("Gráficos de sinais")
    if s["sinal"]:
        JANELA_S = 5
        N_TICKS = 5
        # instante da amostra mais recente = borda direita (0 s); eixo fixo de -5 s a 0 s
        t_ref = max(pts[-1][0] for pts in s["sinal"].values() if pts)
        # 5 marcas fixas igualmente espaçadas na janela (-5, -3.75, -2.5, -1.25, 0 s)
        ticks = [round(-JANELA_S + i * JANELA_S / (N_TICKS - 1), 4) for i in range(N_TICKS)]
        rotulos_t = {k: (t_ref + pd.Timedelta(seconds=k)).strftime("%H:%M:%S") for k in ticks}
        # chaves no formato que toString() do Vega produz ("-5", "-3.75", "0")
        mapa_t = ", ".join(f"'{k:g}': '{v}'" for k, v in rotulos_t.items())
        label_expr_t = "{" + mapa_t + "}[toString(datum.value)]"

        def grafico_sinal(idx, titulo_y):
            linhas = []
            for c, pts in s["sinal"].items():
                nome = nome_cinto(c)
                for p in pts:
                    if len(p) <= idx:
                        continue
                    dt_s = (p[0] - t_ref).total_seconds()
                    if dt_s < -JANELA_S:
                        continue
                    linhas.append({"t": dt_s, "valor": p[idx], "cinto": nome,
                                   "horario": p[0].strftime("%H:%M:%S.%f")[:-3]})
            df = pd.DataFrame(linhas)
            return alt.Chart(df).mark_line().encode(
                x=alt.X("t:Q", title="Horário",
                        scale=alt.Scale(domain=[-JANELA_S, 0], nice=False),
                        axis=alt.Axis(values=ticks, labelExpr=label_expr_t,
                                      labelAngle=-45, grid=True)),
                y=alt.Y("valor:Q", title=titulo_y),
                color=alt.Color("cinto:N", title="Legenda"),
                tooltip=[alt.Tooltip("horario:N", title="Horário"),
                         alt.Tooltip("cinto:N", title="Cinto"),
                         alt.Tooltip("valor:Q", title=titulo_y, format=".2f")],
            ).properties(height=220)

        g1, g2 = st.columns(2)
        with g1:
            st.caption("Acelerômetro |a| - Últimos 5s")
            st.altair_chart(grafico_sinal(1, "|a|"), width="stretch")
        with g2:
            st.caption("Giroscópio |ω| (°/s) — Últimos 5s")
            st.altair_chart(grafico_sinal(2, "|ω| (°/s)"), width="stretch")
        st.caption("ECG bruto (AD8232) — Últimos 5s")
        st.altair_chart(grafico_sinal(3, "ADC (0–4095)"), width="stretch")
    else:
        st.caption("Sem dados de sinal para plotar.")

    with st.expander("Tabela RSSI por cinto × antena"):
        if s["tabela"]:
            df_rssi = pd.DataFrame(s["tabela"]).rename(columns={"idade (s)": "Janela de Conexão (s)"})
            st.dataframe(df_rssi, width="stretch", hide_index=True)
        else:
            st.caption("Sem tabela RSSI disponível.")

    with st.expander("Histórico de quedas"):
        if s["quedas"]:
            st.dataframe(pd.DataFrame(s["quedas"]), width="stretch", hide_index=True)
        else:
            st.caption("Nenhuma queda registrada.")

    st.subheader("Exportação de dados")
    d1, d2, d3 = st.columns(3)
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    with d1:
        st.download_button(f"Janelas analisadas ({s['n_janelas']})", cx.janelas_csv(),
                           file_name=f"janelas_{tag}.csv", mime="text/csv",
                           disabled=not s["n_janelas"], width="stretch")
    with d2:
        cols_q = ["data", "hora", "cinto", "antena", "prob", "amax (g)", "tilt (graus)"]
        st.download_button(f"Quedas detectadas ({len(s['quedas'])})", _para_csv(s["quedas"], cols_q),
                           file_name=f"quedas_{tag}.csv", mime="text/csv",
                           disabled=not s["quedas"], width="stretch")
    with d3:
        g = cx.status_gravacao()
        if g["ativa"]:
            st.button("Amostras: pare a gravação para baixar", disabled=True, width="stretch")
        elif g["ultima"]:
            partes = [p for p in g["ultima"]["partes"] if os.path.exists(p["caminho"])]
            if not partes:
                st.button("Amostras: arquivos da última gravação não encontrados", disabled=True, width="stretch")
            for i, p in enumerate(partes, 1):
                st_ = os.stat(p["caminho"])
                rotulo = (f"Amostras da última gravação ({p['n']})" if len(partes) == 1
                          else f"Amostras — parte {i}/{len(partes)} ({p['n']})")
                st.download_button(rotulo, _ler_arquivo(p["caminho"], st_.st_mtime, st_.st_size),
                                   file_name=os.path.basename(p["caminho"]), mime="text/csv",
                                   width="stretch", key=f"dl_parte_{i}")
        else:
            st.button("Amostras: use 'Gravar amostras' na barra lateral", disabled=True,
                      width="stretch")
    st.caption(f"As gravações ficam também na pasta {os.path.abspath(PASTA_GRAVACOES)}. "
               f"O CSV de amostras é dividido em partes (_p01, _p02, ...) a cada {ROTACAO_MIN} min.")

if auto:
    time.sleep(intervalo)
    st.rerun()
