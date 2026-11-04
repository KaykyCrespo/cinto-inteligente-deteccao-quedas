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
  - "Gravar amostras" salva um único CSV em gravacoes/amostras_<data>_pNN.csv com
    cada pacote recebido: os do GATT (sensores completos) e os só-RSSI das antenas
    não conectadas (sensores em branco). A coluna "origem" diz qual é qual.
  - A seção "Exportação de dados" baixa as janelas analisadas (em memória), as
    quedas e a última gravação de amostras.
"""

import csv
import hashlib
import io
import math
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from html import escape

import altair as alt
import joblib
import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

from interface_mvp_2 import TOPIC_BASE, parse_pacote_mvp
import alerta_telegram as tg
import localizacao as loc

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
AMOSTRA_COLS = ["timestamp", "origem", "id_cinto", "id_antena", "rssi", "seq", "ax", "ay", "az",
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
        self.total_quedas = 0
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
        self.grav = None            # {"amostras": (arquivo, writer, caminho), "n": int, "parte": int, ...}
        self.ultima_gravacao = None # caminhos da última gravação encerrada

        # alerta Telegram (ligado/desligado pela barra lateral)
        self.telegram_ativo = False
        self.telegram_geracao = 0
        self.fechada = False
        self.tg_status = None       # {"hora", "ok", "erro", "tipo"} do último envio

        # localização por RSSI (quadrante)
        self.loc = loc.Localizador()

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
            g["amostras"][0].close()
            g["partes"].append({"caminho": g["amostras"][2], "n": g["n_parte"]})
            self.ultima_gravacao = {"amostras": g["amostras"][2], "partes": g["partes"], "n": g["n"]}
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
                w.writerow({"timestamp": agora.isoformat(timespec="milliseconds"),
                            "origem": "anuncio" if somente_rssi else "gatt", **d})
                self.grav["n"] += 1
                self.grav["n_parte"] += 1
                if self.grav["n_parte"] % 200 == 0:
                    f.flush()
            e = self.estado.setdefault((cinto, antena), {"rssi": [], "t": 0, "gatt": False})
            e["rssi"] = (e["rssi"] + [d["rssi"]])[-RSSI_WINDOW:]
            e["t"] = t
            e["gatt"] = not somente_rssi
        self.loc.atualizar(cinto, antena, d["rssi"], t, gatt=not somente_rssi)

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
            self.hist_prob.setdefault(cinto, deque(maxlen=HIST_MAX)).append((agora, j["prob"]))
            if j["queda"]:
                self.total_quedas += 1
                self.quedas.appendleft({
                    "data": agora.strftime("%Y-%m-%d"),
                    "hora": agora.strftime("%H:%M:%S"), "cinto": cinto, "antena": j["anchor"],
                    "prob": round(j["prob"], 4), "amax (g)": j["features"]["amax"],
                    "gmax": j["features"]["gmax"],
                    "tilt (graus)": j["features"]["tilt"],
                })
                self._evento(f"QUEDA cinto {cinto} prob {j['prob']:.1%} perto da antena {j['anchor']}")
                enviar_tg = self.telegram_ativo and tg.configurado()
                geracao_tg = self.telegram_geracao
                rssi_anchor = self.detector.rssi[cinto].get(j["anchor"])
        if j["queda"]:
            pos = self.loc.estimar(cinto, t)
            local_queda = pos["nome"] if pos else None
            if pos and pos["confianca"] == "baixa":
                local_queda += " (última posição, baixa confiança)"
            with self.lock:
                self.quedas[0]["quadrante"] = local_queda or "localização indisponível"
        if j["queda"] and enviar_tg:
            texto = tg.mensagem_queda(nome_cinto(cinto), agora, j["anchor"], rssi_anchor,
                                      j["prob"], j["features"]["amax"], j["features"]["tilt"],
                                      quadrante=local_queda)
            tg.enviar(texto, callback=lambda ok, erro: self._tg_resultado(ok, erro, "queda"),
                      permitido=lambda: self._telegram_permitido(geracao_tg))

    def configurar_telegram(self, ativo):
        with self.lock:
            ativo = bool(ativo)
            if self.telegram_ativo != ativo:
                self.telegram_geracao += 1
            self.telegram_ativo = ativo

    def _telegram_permitido(self, geracao):
        with self.lock:
            return (not self.fechada and self.detectar and self.telegram_ativo
                    and self.telegram_geracao == geracao and tg.configurado())

    def _tg_resultado(self, ok, erro, tipo):
        with self.lock:
            self.tg_status = {"hora": datetime.now(), "ok": ok, "erro": erro, "tipo": tipo}
            self._evento(f"Telegram ({tipo}): {'enviado' if ok else 'FALHOU - ' + str(erro)}")

    def testar_telegram(self):
        tg.enviar(tg.mensagem_teste(), callback=lambda ok, erro: self._tg_resultado(ok, erro, "teste"))

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
            cintos_vistos = {c for c, _ in self.estado}
            posicoes = {c: self.loc.estimar(c, agora) for c in cintos_vistos}
            raios = {c: self.loc.raios(c, agora) for c in cintos_vistos}
            return {
                "tabela": linhas, "melhores": melhores, "posicoes": posicoes, "raios": raios,
                "sinal": {c: list(s) for c, s in self.sinal.items()},
                "hist": {c: list(h) for c, h in self.hist_prob.items()},
                "taxa": {c: tx["hz"] for c, tx in self.taxa.items()},
                "quedas": list(self.quedas), "total_quedas": self.total_quedas, "eventos": list(self.eventos),
                "anchors": dict(self.anchors_status), "total": self.total, "invalidos": self.invalidos,
                "conectado": self.conectado, "erro": self.erro, "faixa": self.faixa,
                "tg_status": dict(self.tg_status) if self.tg_status else None,
                "telegram_ativo": self.telegram_ativo,
                "perdas": {c: det.taxa_perda(c) for c in det.amostras} if det else {},
                "resets": dict(det.resets) if det else {},
                "n_janelas": len(self.janelas),
            }

    def janelas_csv(self):
        with self.lock:
            linhas = list(self.janelas)
        return _para_csv(linhas, JANELA_COLS)

    def fechar(self):
        with self.lock:
            self.fechada = True
            self.telegram_ativo = False
            self.telegram_geracao += 1
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
def _limiar_do_modelo(caminho, mtime):
    return float(joblib.load(caminho).get("limiar", 0.5))


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
            h["cx"].configurar_telegram(h.get("telegram_ativo", False))
        h["params"] = params
        h["versao"] = _VERSAO_CONEXAO
    return h["cx"]


def atualizar_alertas_telegram():
    h = _holder()
    h["telegram_ativo"] = bool(st.session_state["enviar_alerta_queda"])
    if "cx" in h:
        h["cx"].configurar_telegram(h["telegram_ativo"])


def nome_cinto(cinto):
    try:
        return f"OQPNB{int(cinto):02d}"
    except (TypeError, ValueError):
        return str(cinto)


def queda_em_alerta(quedas, cinto, minutos, agora=None):
    ultima = next((queda for queda in quedas if str(queda["cinto"]) == str(cinto)), None)
    if ultima is None:
        return None
    instante = datetime.strptime(f"{ultima['data']} {ultima['hora']}", "%Y-%m-%d %H:%M:%S")
    idade = ((datetime.now() if agora is None else agora) - instante).total_seconds()
    return ultima if idade < minutos * 60 else None


def aviso_queda(queda, cinto, minutos, agora=None):
    instante = datetime.strptime(f"{queda['data']} {queda['hora']}", "%Y-%m-%d %H:%M:%S")
    idade = ((datetime.now() if agora is None else agora) - instante).total_seconds()
    restantes = max(0, math.ceil(minutos * 60 - idade))
    minutos_restantes, segundos_restantes = divmod(restantes, 60)
    quadrante = queda.get("quadrante") or "Indisponível"
    if quadrante.casefold() == "localização indisponível":
        quadrante = "Indisponível"
    return (
        '<div role="alert" style="background:rgba(239,68,68,0.10);'
        'border:1px solid rgba(239,68,68,0.25);border-left:3px solid #ef6c6c;'
        'border-radius:8px;padding:14px;font-size:0.875rem;line-height:1.6">'
        '<div style="color:#ef6c6c;font-size:0.95rem;font-weight:600;margin-bottom:8px">'
        '🚨 POSSÍVEL QUEDA</div>'
        f'<div style="margin-bottom:8px">Cinto <strong>{escape(nome_cinto(cinto))}</strong>'
        f' · Probabilidade <strong>{queda["prob"]:.1%}</strong></div>'
        '<div style="display:flex;flex-wrap:wrap;column-gap:16px">'
        f'<span>Data: <strong>{instante:%d/%m/%Y}</strong></span>'
        f'<span>Hora: <strong>{instante:%H:%M:%S}</strong></span></div>'
        '<div style="display:flex;flex-wrap:wrap;column-gap:16px">'
        f'<span>Antena: <strong>{escape(str(queda["antena"]))}</strong></span>'
        f'<span>Quadrante: <strong>{escape(quadrante)}</strong></span></div>'
        '<div style="opacity:0.7;font-size:0.8rem;margin-top:8px">'
        f'Aviso visual encerra em {minutos_restantes}min {segundos_restantes:02d}s</div></div>'
    )


def mostrar_gravacao():
    g = cx.status_gravacao()
    status_gravacao = st.empty()
    if g["ativa"]:
        status_gravacao.success(f"Gravando: {g['n']} amostras ({g['seg'] / 60:.0f} min) — parte {g['parte']}")
    if st.button("Parar gravação" if g["ativa"] else "Gravar amostras", width="stretch",
                 type="primary" if g["ativa"] else "secondary", key="btn_gravacao"):
        if g["ativa"]:
            cx.parar_gravacao()
        else:
            cx.iniciar_gravacao()
        st.rerun(scope="app")


# ================= Interface =================
st.set_page_config(page_title="Monitor OQPNB", page_icon="🩺", layout="wide")

with st.sidebar:
    st.html("""<style>
        [data-testid="stSidebar"] hr {margin: 0.5rem 0 !important;}
        [data-testid="stSidebar"] h2 {padding-top: 0.25rem;}
    </style>""")
    col_logo, col_nome = st.columns([1, 2], gap="small", vertical_alignment="center")
    with col_logo:
        st.image(os.path.join(os.path.dirname(__file__), "assets", "logo_oqpnb.svg"), width=72)
    with col_nome:
        st.markdown('<div style="font-size:1rem;font-weight:600;white-space:nowrap">Cinto Inteligente</div>',
                    unsafe_allow_html=True)
    st.header("Alertas de queda")
    tg_ok = tg.configurado()
    h = _holder()
    st.session_state["enviar_alerta_queda"] = bool(h.setdefault("telegram_ativo", tg_ok) and tg_ok)
    telegram_ativo = st.toggle("Enviar alerta de quedas", key="enviar_alerta_queda",
                              disabled=not tg_ok, on_change=atualizar_alertas_telegram)
    telegram_box = st.container()
    if not tg_ok:
        st.caption("Defina OQPNB_TG_TOKEN e OQPNB_TG_CHAT antes de abrir o app.")
    if os.path.exists(MODELO):
        limiar_modelo = _limiar_do_modelo(MODELO, os.stat(MODELO).st_mtime_ns)
        valor_modelo = f"{limiar_modelo:.2f}".replace(".", ",")
        titulo_limiar = f"Limiar de alarme (0 = modelo: {valor_modelo} / {limiar_modelo:.0%})"
    else:
        titulo_limiar = "Limiar de alarme (0 = modelo indisponível)"
    limiar = st.slider(titulo_limiar, 0.0, 1.0, 0.50, 0.05)
    tempo_reset_alerta = st.slider("Tempo para resetar alerta (min)", 1, 5, 2, 1)
    st.divider()
    st.header("Tela")
    auto = st.toggle("Atualizar automaticamente", value=True)
    intervalo = st.slider("Intervalo (s)", 0.5, 5.0, 1.0, 0.5)
    st.divider()
    params = (BROKER, PORT, True, limiar or None)
    cx = conectar(*params)
    st.header("Gravação de amostras")
    st.fragment(run_every=intervalo if auto else None)(mostrar_gravacao)()
    if st.button("Reconectar", width="stretch", type="primary"):
        h = _holder()
        if "cx" in h:
            h["cx"].fechar()
        manter_telegram = h.get("telegram_ativo", False)
        h.clear()
        h["telegram_ativo"] = manter_telegram
        st.rerun()

with telegram_box:
    st.button("Testar envio", width="stretch", disabled=not tg_ok,
              key="btn_tg_teste", on_click=cx.testar_telegram)

@st.fragment(run_every=intervalo if auto else None)
def atualizar_painel():
    s = cx.snapshot()

    monitor_tab, detalhes_tab = st.tabs(["Monitoramento", "Detalhes"])

    with monitor_tab:
        if s["erro"]:
            st.error(f"Erro MQTT: {s['erro']}")
        if s["invalidos"]:
            st.warning(f"{s['invalidos']} pacotes com formato inválido (veja os eventos abaixo).")

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
                        cabecalho, status_cinto = st.columns([3, 2])
                        with cabecalho:
                            st.markdown(f"### CINTO {nome_exibicao}")
                            if s["faixa"]:
                                st.caption(f"Cinto configurado: {s['faixa']}")
                        with status_cinto:
                            with st.container(height=220, border=False):
                                agora_alerta = datetime.now()
                                ultima_queda = queda_em_alerta(s["quedas"], cinto, tempo_reset_alerta, agora_alerta)
                                if ultima_queda:
                                    st.markdown(aviso_queda(ultima_queda, cinto, tempo_reset_alerta, agora_alerta),
                                                unsafe_allow_html=True)
                                else:
                                    st.markdown(
                                        '<div style="display:flex;justify-content:flex-end">'
                                        '<span style="color:#2eae67;background:rgba(46,174,103,0.16);'
                                        'border-radius:8px;padding:6px 10px;font-size:0.875rem">'
                                        'STATUS: NORMAL</span></div>', unsafe_allow_html=True)
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Broker", "Conectado" if s["conectado"] else "Desconectado")
                        c2.metric("Amostras recebidas", f"{s['total']:,}".replace(",", "."))
                        c2.metric("Taxa", f"{s['taxa'].get(cinto, 0):.0f} Hz")
                        c3.metric("Cintos ativos", len(s["melhores"]))
                        c3.markdown("Status Eletrodo")
                        if last.get("eletrodos_conectados") == 0:
                            c3.markdown(
                                '<span style="display:inline-block;color:#e6b422;'
                                'background:rgba(230,180,34,0.18);border-radius:8px;padding:2px 8px">'
                                'SOLTO</span>', unsafe_allow_html=True)
                        elif last.get("eletrodos_conectados") == 1:
                            c3.markdown(
                                '<span style="display:inline-block;color:#2eae67;'
                                'background:rgba(46,174,103,0.18);border-radius:8px;padding:2px 8px">'
                                'CONECTADO</span>', unsafe_allow_html=True)
                        else:
                            c3.caption("Indisponível")
                        c4.metric("Antenas online", sum(1 for v in s["anchors"].values() if v == "online"))
                        c4.markdown("Status Telegram")
                        if s["telegram_ativo"] and tg.configurado():
                            c4.markdown(
                                '<span style="display:inline-block;color:#2eae67;'
                                'background:rgba(46,174,103,0.18);border-radius:8px;padding:2px 8px">'
                                'Ativado Bot</span>', unsafe_allow_html=True)
                        else:
                            c4.markdown(
                                '<span style="display:inline-block;color:#e6b422;'
                                'background:rgba(230,180,34,0.18);border-radius:8px;padding:2px 8px">'
                                'Desativado Bot</span>', unsafe_allow_html=True)
                        pos = s["posicoes"].get(cinto)
                        c1.metric("Quadrante", pos["quadrante"] if pos else "—",
                                 pos["nome"] if pos else "aguardando 3 antenas consistentes", delta_color="off")
                        progresso_queda = st.empty()
                        if prob is not None:
                            progresso_queda.progress(min(max(prob, 0.0), 1.0), text=f"Prob. queda: {prob:.1%}")
                        leitura_ecg = st.empty()
                        if last.get("eletrodos_conectados") != 0:
                            leitura_ecg.caption(f"ECG (AD8232): {last.get('sinal_ad8232')}")
                        aviso_perdas = st.empty()
                        if s["perdas"].get(cinto, 0) > 0.05:
                            aviso_perdas.warning(f"{100 * s['perdas'][cinto]:.0f}% das amostras perdidas")
                        ultima_leitura = st.empty()
                        if s["resets"].get(cinto):
                            ultima_leitura.caption(f"Janela reiniciada {s['resets'][cinto]}x por buraco nos dados | Última leitura há {m['idade']:.1f}s")
                        else:
                            ultima_leitura.caption(f"Última leitura há {m['idade']:.1f}s")

        col_probabilidade, col_quedas = st.columns([1, 1])
        col_probabilidade.subheader("Probabilidade de Queda")
        N_PROB = 8
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
                    rotulo_limiar = f"Limiar de alerta ({cx.detector.limiar:.0%})"
                    dominio.append(rotulo_limiar)
                    cores.append("red")
                escala_cor = alt.Scale(domain=dominio, range=cores)
                eixo_probabilidade = alt.Axis(
                    format=".0%", values=[i / 10 for i in range(11)],
                    labelOverlap=False, labelBound=False)
                base = alt.Chart(df).encode(
                    x=alt.X("pos:Q", title="Horário",
                            scale=alt.Scale(domain=[-(N_PROB - 1), 0], nice=False),
                            axis=alt.Axis(values=list(range(-(N_PROB - 1), 1)), labelExpr=label_expr,
                                          labelAngle=-45, grid=True)),
                    y=alt.Y("probabilidade:Q", title="Probabilidade",
                        scale=alt.Scale(domain=[0, 1], nice=False),
                        axis=eixo_probabilidade),
                    color=alt.Color("cinto:N", title=None, scale=escala_cor),
                    tooltip=[
                        alt.Tooltip("horario_label:N", title="Horário"),
                        alt.Tooltip("data_label:N", title="Data"),
                        alt.Tooltip("cinto:N", title="Cinto"),
                        alt.Tooltip("probabilidade:Q", title="Probabilidade", format=".1%"),
                    ],
                )
                chart = base.mark_line() + base.mark_point(filled=True, size=60)
                if cx.detector is not None:
                    limiar_df = pd.DataFrame({"y": [cx.detector.limiar], "cinto": [rotulo_limiar]})
                    chart += alt.Chart(limiar_df).mark_rule(strokeDash=[6, 4], strokeWidth=2).encode(
                        y=alt.Y("y:Q", axis=eixo_probabilidade),
                        color=alt.Color("cinto:N", title=None, scale=escala_cor),
                        tooltip=[alt.Tooltip("y:Q", title="Limiar", format=".1%")])
                chart_spec = chart.properties(height=400).configure_legend(
                    orient="top", direction="horizontal", offset=12).to_dict()
                chart_spec["config"]["legend"]["layout"] = {"top": {"anchor": "middle"}}
                col_probabilidade.vega_lite_chart(chart_spec, width="stretch")
            else:
                col_probabilidade.caption("Nenhuma probabilidade de queda registrada.")
        else:
            col_probabilidade.caption("Nenhuma probabilidade de queda registrada.")

        # -------- quedas detectadas --------
        col_quedas.subheader("Quedas Detectadas")
        if s["quedas"]:
            df_quedas = pd.DataFrame(s["quedas"]).reindex(
                columns=["data", "hora", "cinto", "antena", "prob", "amax (g)", "gmax", "quadrante"])
            df_quedas["data"] = pd.to_datetime(df_quedas["data"], format="%Y-%m-%d", errors="coerce").dt.strftime("%d/%m/%Y")
            df_quedas["prob"] = df_quedas["prob"].map(lambda valor: f"{valor:.1%}")
            df_quedas["quadrante"] = (
                df_quedas["quadrante"].fillna("Indisponível")
                .str.removesuffix(" (última posição, baixa confiança)")
                .replace({"localização indisponível": "Indisponível", "": "Indisponível"}))
            df_quedas = df_quedas.rename(columns={
                "data": "Data", "hora": "Hora", "cinto": "Cinto", "antena": "Antena", "prob": "Prob",
                "amax (g)": "|a| Máx(g)", "gmax": "|w| Giros(º/s)", "quadrante": "Quadrate"})
            col_quedas.dataframe(df_quedas, width="stretch", hide_index=True)
        else:
            col_quedas.caption("Nenhuma queda detectada.")

    with detalhes_tab:
        def _por_cinto(d, fmt):
            if not d:
                return "—"
            if len(d) == 1:
                return fmt(next(iter(d.values())))
            return " | ".join(f"{nome_cinto(k)}: {fmt(v)}" for k, v in sorted(d.items()))

        st.subheader("Status do Sistema")
        status_sistema = st.container(border=True)
        col1, col2, col_invalidos, col3, col4 = status_sistema.columns(5)
        col1.metric("Broker", "Conectado" if s["conectado"] else "Desconectado")
        col1.metric("Quadrante", _por_cinto(
            {cinto: pos["quadrante"] if pos else "—" for cinto, pos in s["posicoes"].items()}, str))
        col2.metric("Amostras recebidas", f"{s['total']:,}".replace(",", "."))
        col2.metric("Taxa", _por_cinto(s["taxa"], lambda valor: f"{valor:.0f} Hz"))
        col_invalidos.metric("Pacotes inválidos", s["invalidos"])
        col_invalidos.metric("Amostras perdidas", _por_cinto(s["perdas"], lambda v: f"{100 * v:.1f}%"))
        if cx.detector is not None:
            col3.markdown("Modelo")
            col3.markdown(
                '<div style="font-size:1rem;line-height:1.5;overflow-wrap:anywhere">'
                f'{escape(os.path.basename(MODELO))}</div>', unsafe_allow_html=True)
            col3.caption(f"Limiar: {cx.detector.limiar:.2f}")
        else:
            col3.metric("Modelo", "desligado")
            col3.caption(os.path.basename(MODELO) if os.path.exists(MODELO) else f"{MODELO} não encontrado")
        col3.metric("Janelas reiniciadas", _por_cinto(s["resets"], lambda v: f"{v}"))
        col4.markdown("Telegram")
        if s["telegram_ativo"] and tg.configurado():
            col4.markdown(
                '<span style="display:inline-block;color:#2eae67;'
                'background:rgba(46,174,103,0.18);border-radius:8px;padding:2px 8px">'
                'Ativado Bot</span>', unsafe_allow_html=True)
        else:
            col4.markdown(
                '<span style="display:inline-block;color:#e6b422;'
                'background:rgba(230,180,34,0.18);border-radius:8px;padding:2px 8px">'
                'Desativado Bot</span>', unsafe_allow_html=True)
        col4.metric("Quantidade de quedas", f"{s['total_quedas']:,}".replace(",", "."))
        if s["tg_status"]:
            t_ = s["tg_status"]
            col4.caption(f"último envio ({t_['tipo']}) {t_['hora']:%H:%M:%S}: "
                         + ("OK" if t_["ok"] else f"falhou — {t_['erro']}"))

        if s["erro"]:
            status_sistema.error(f"Erro MQTT: {s['erro']}")

        col_cinto, col_antenas = status_sistema.columns([1, 2])
        ALT_CARD = 320                       # mesma altura para o card do cinto e o das antenas

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
                            if last.get("eletrodos_conectados") == 0:
                                st.markdown(
                                    'Status eletrodo: <span style="color:#e6b422;'
                                    'background:rgba(230,180,34,0.18);border-radius:8px;padding:2px 8px">'
                                    'SOLTO</span>', unsafe_allow_html=True)
                            elif last.get("eletrodos_conectados") == 1:
                                st.markdown(
                                    'Status eletrodo: <span style="color:#2eae67;'
                                    'background:rgba(46,174,103,0.18);border-radius:8px;padding:2px 8px">'
                                    'CONECTADO</span>', unsafe_allow_html=True)
                            else:
                                st.markdown("Status eletrodo: Indisponível")
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
            antenas_mais_perto = {str(m["antena"]) for m in s["melhores"].values()
                                  if status_antenas.get(str(m["antena"])) != "offline"}
            # RSSI mais recente visto por cada antena (de qualquer cinto)
            rssi_antena = {}
            for linha in s["tabela"]:
                a = str(linha["antena"])
                if linha["RSSI atual"] is not None and (a not in rssi_antena or linha["idade (s)"] < rssi_antena[a][1]):
                    rssi_antena[a] = (linha["RSSI atual"], linha["idade (s)"], linha["origem"])
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
                    modo = ("GATT" if r[2] == "GATT" else "ADVERTISING") if r and r[1] <= 10 and status != "offline" else "sem dados recentes"
                    cor_modo = "#4e9be8" if modo == "GATT" else "#c89120" if modo == "ADVERTISING" else "gray"
                    with col:
                        marca_proxima = ' <span style="color:gray;font-size:0.875rem">(Mais perto)</span>' if str(antena) in antenas_mais_perto else ""
                        st.markdown(f"**Anchor {antena}**{marca_proxima}", unsafe_allow_html=True)
                        st.markdown(f":{cor}[● {badge}]")
                        st.markdown(f'Modo: <span style="color:{cor_modo}">{modo}</span>', unsafe_allow_html=True)
                        st.metric("RSSI", f"{r[0]} dBm" if r else "—",
                                  f"há {r[1]:.0f} s" if r else None, delta_color="off",
                                  label_visibility="collapsed")

        with st.expander("Tabela RSSI por Cinto × Antena"):
            if s["tabela"]:
                df_rssi = pd.DataFrame(s["tabela"]).rename(columns={
                    "idade (s)": "Janela de Conexão (s)", "RSSI atual": "RSSI Atual", "RSSI médio": "RSSI Médio"})
                df_rssi = df_rssi.rename(columns=lambda coluna: coluna[:1].upper() + coluna[1:])
                st.dataframe(df_rssi, width="stretch", hide_index=True)
            else:
                st.caption("Sem tabela RSSI disponível.")

        with st.expander("Histórico de Quedas"):
            if s["quedas"]:
                df_historico = pd.DataFrame(s["quedas"])
                df_historico["data"] = pd.to_datetime(df_historico["data"], format="%Y-%m-%d", errors="coerce").dt.strftime("%d/%m/%Y")
                df_historico["prob"] = df_historico["prob"].map(lambda valor: f"{valor:.1%}")
                df_historico = df_historico.rename(columns={"amax (g)": "|a| Máx(g)", "gmax": "|w| Giros(º/s)"})
                df_historico = df_historico.rename(columns=lambda coluna: coluna[:1].upper() + coluna[1:])
                st.dataframe(df_historico, width="stretch", hide_index=True)
            else:
                st.caption("Nenhuma queda registrada.")

        st.subheader("Gráficos de Sinais")
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

            def grafico_sinal(idx, titulo_y, titulo, altura=360):
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
                chart = alt.Chart(df).mark_line().encode(
                    x=alt.X("t:Q", title="Horário",
                            scale=alt.Scale(domain=[-JANELA_S, 0], nice=False),
                            axis=alt.Axis(values=ticks, labelExpr=label_expr_t,
                                          labelAngle=-45, grid=True)),
                        y=alt.Y("valor:Q", title=titulo_y,
                            axis=alt.Axis(tickCount=5, labelOverlap=False)),
                    color=alt.Color("cinto:N", title=None,
                                    legend=alt.Legend(title=None, orient="top", direction="horizontal")),
                    tooltip=[alt.Tooltip("horario:N", title="Horário"),
                             alt.Tooltip("cinto:N", title="Cinto"),
                             alt.Tooltip("valor:Q", title=titulo_y, format=".2f")],
                ).properties(height=altura, title=alt.TitleParams(text=titulo, anchor="middle", offset=12))
                spec = chart.configure_legend(orient="top", direction="horizontal", offset=8).to_dict()
                spec["config"]["legend"]["layout"] = {"top": {"anchor": "middle"}}
                return spec

            g1, g2 = st.columns(2)
            with g1:
                st.vega_lite_chart(grafico_sinal(1, "|a|", "Acelerômetro |a| - Últimos 5s"), width="stretch")
            with g2:
                st.vega_lite_chart(grafico_sinal(2, "|ω| (°/s)", "Giroscópio |ω| (°/s) - Últimos 5s"), width="stretch")
        else:
            st.caption("Sem dados de sinal para plotar.")

        col_localizacao, col_ecg = st.columns(2)
        with col_localizacao:
            st.subheader("Localização indoor")
            L = loc.LADO_M
            anc_df = pd.DataFrame([{"x": x, "y": y, "rotulo": f"Anchor {i}"} for i, (x, y) in loc.ANCHORS.items()])
            quad_df = pd.DataFrame([
                {"x": L / 4, "y": 3 * L / 4, "q": "SE"}, {"x": 3 * L / 4, "y": 3 * L / 4, "q": "SD"},
                {"x": L / 4, "y": L / 4, "q": "IE"}, {"x": 3 * L / 4, "y": L / 4, "q": "ID"}])
            pos_rows = []
            for c, p in s["posicoes"].items():
                if p:
                    pos_rows.append({"x": p["x"], "y": p["y"], "rotulo": nome_cinto(c), "quadrante": p["nome"],
                                     "anchors": p["n_anchors"], "erro": p["erro_m"],
                                     "confianca": p["confianca"], "idade": p["idade_s"]})
            quad_df["ativo"] = quad_df["q"].isin([p["quadrante"] for p in s["posicoes"].values()
                                               if p and p["confianca"] == "boa"])
            esc_x = alt.Scale(domain=[-0.5, L + 0.5], nice=False)
            esc_y = alt.Scale(domain=[-0.5, L + 0.5], nice=False)
            quad_df["x1"] = quad_df["x"] - L / 4; quad_df["x2"] = quad_df["x"] + L / 4
            quad_df["y1"] = quad_df["y"] - L / 4; quad_df["y2"] = quad_df["y"] + L / 4
            fundo = alt.Chart(quad_df).mark_rect(stroke="#888", strokeWidth=1).encode(
                x=alt.X("x1:Q", scale=esc_x, title="x (m)"), x2="x2:Q",
                y=alt.Y("y1:Q", scale=esc_y, title="y (m)"), y2="y2:Q",
                color=alt.condition("datum.ativo", alt.value("#2e7d32"), alt.value("#2b2b2b")),
                tooltip=[alt.Tooltip("q:N", title="Quadrante")])
            rot_q = alt.Chart(quad_df).mark_text(color="#bbb", fontSize=14).encode(x="x:Q", y="y:Q", text="q:N")
            anc_pts = alt.Chart(anc_df).mark_point(shape="triangle-up", size=250, filled=True, color="#f58518").encode(
                x="x:Q", y="y:Q", tooltip=["rotulo:N"])
            anc_txt = alt.Chart(anc_df).mark_text(dy=-16, color="#f58518").encode(x="x:Q", y="y:Q", text="rotulo:N")
            mapa = fundo + rot_q + anc_pts + anc_txt
            # círculos de distância estimada: a interseção indica a região provável do cinto
            circ_rows = []
            angulos = [2 * math.pi * k / 72 for k in range(73)]
            for c, por_antena in s.get("raios", {}).items():
                if not por_antena:
                    continue
                mais_forte = max(por_antena, key=lambda a: por_antena[a]["rssi"])
                for a, info in por_antena.items():
                    ax_, ay_ = loc.ANCHORS[a]
                    # antena longe/sombreada só exclui região; desenha fraca para não dominar o mapa
                    tipo = "perto" if a == mais_forte else ("longe" if info["dist"] > L else "media")
                    for k, ang in enumerate(angulos):
                        circ_rows.append({"x": ax_ + info["dist"] * math.cos(ang), "y": ay_ + info["dist"] * math.sin(ang),
                                          "k": k, "serie": f"{nome_cinto(c)}-A{a}", "antena": f"A{a}", "tipo": tipo,
                                          "raio": round(info["dist"], 2), "rssi": info["rssi"]})
            if circ_rows:
                tipos = ["perto", "media", "longe"]
                mapa += alt.Chart(pd.DataFrame(circ_rows)).mark_line(clip=True).encode(
                    x="x:Q", y="y:Q", order="k:Q", detail="serie:N", color=alt.value("#f58518"),
                    opacity=alt.Opacity("tipo:N", scale=alt.Scale(domain=tipos, range=[0.95, 0.6, 0.2]), legend=None),
                    strokeDash=alt.StrokeDash("tipo:N", scale=alt.Scale(domain=tipos, range=[[1, 0], [6, 4], [2, 4]]), legend=None),
                    strokeWidth=alt.StrokeWidth("tipo:N", scale=alt.Scale(domain=tipos, range=[2.5, 1.5, 1]), legend=None),
                    tooltip=[alt.Tooltip("antena:N", title="Antena"), alt.Tooltip("raio:Q", title="Raio (m)", format=".1f"),
                             alt.Tooltip("rssi:Q", title="RSSI (dBm)", format=".0f")])
            if pos_rows:
                pos_df = pd.DataFrame(pos_rows)
                mapa += alt.Chart(pos_df).mark_point(size=300, filled=True).encode(
                    x="x:Q", y="y:Q",
                    color=alt.Color("confianca:N", title="Confiança",
                                    scale=alt.Scale(domain=["boa", "baixa"], range=["#4c78a8", "#e6a23c"])),
                    tooltip=[alt.Tooltip("rotulo:N", title="Cinto"), alt.Tooltip("quadrante:N", title="Quadrante"),
                             alt.Tooltip("x:Q", format=".1f"), alt.Tooltip("y:Q", format=".1f"),
                             alt.Tooltip("confianca:N", title="Confiança"),
                             alt.Tooltip("idade:Q", title="Idade da posição (s)", format=".1f"),
                             alt.Tooltip("anchors:Q", title="Anchors usadas")])
                mapa += alt.Chart(pos_df).mark_text(dy=18, color="#4c78a8").encode(x="x:Q", y="y:Q", text="rotulo:N")
            st.altair_chart(mapa.properties(height=420, width=420), width="content")
            for c, p in sorted(s["posicoes"].items()):
                raios_c = s.get("raios", {}).get(c, {})
                if raios_c:
                    st.caption("Raios atuais: " + ", ".join(
                        f"A{a} {r['rssi']:.0f} dBm → {'≥ ' if r['limitado'] else ''}{r['dist']:.1f} m"
                        for a, r in sorted(raios_c.items())))
                if not p:
                    st.info(f"{nome_cinto(c)}: localização indisponível; aguardando leituras consistentes de 3 antenas")
                    continue
                with st.container(border=True):
                    st.markdown(f"**{nome_cinto(c)}** → **{p['nome']}** ({p['quadrante']})")
                    if p["confianca"] == "baixa":
                        st.warning(f"Baixa confiança: {p['motivo']}")
                        st.caption(f"Última posição válida há {p['idade_s']:.1f} s; valores abaixo são dessa posição.")
                    else:
                        st.caption("Confiança: boa")
                    st.caption("RSSI suavizado: " + ", ".join(f"A{a} {r:.0f} dBm" for a, r in sorted(p["rssi"].items())))
                    st.caption("Distância estimada: " + ", ".join(f"A{a} {d:.1f} m" for a, d in sorted(p["distancias"].items())))
                    if p["erro_m"] is not None:
                        st.caption(f"Resíduo do ajuste: {p['erro_m']:.1f} m | anchors: {p['n_anchors']}")
            st.caption(f"Lado {L:g} m · RSSI@1m {loc.RSSI_1M:g} dBm · n = {loc.N_PERDA:g} · mediana {loc.JANELA_S:g} s")
        with col_ecg:
            if s["sinal"]:
                st.vega_lite_chart(grafico_sinal(3, "ADC (0–4095)", "ECG bruto (AD8232) - Últimos 5s", altura=380), width="stretch")
            else:
                st.markdown('<h3 style="text-align:center">ECG bruto (AD8232)</h3>', unsafe_allow_html=True)
                st.caption("Sem dados de ECG para plotar.")

        st.subheader("Exportação de dados")
        d1, d2, d3 = st.columns(3)
        tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        with d1:
            st.download_button(f"Janelas analisadas ({s['n_janelas']})", cx.janelas_csv(),
                               file_name=f"janelas_{tag}.csv", mime="text/csv",
                               disabled=not s["n_janelas"], width="stretch")
        with d2:
            cols_q = ["data", "hora", "cinto", "antena", "quadrante", "prob", "amax (g)", "tilt (graus)"]
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


atualizar_painel()
