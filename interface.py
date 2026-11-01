"""
interface.py - Monitor dos anchors OQPNB via MQTT (Mosquitto)

Assina os tópicos publicados pelos anchors (anchor_v3):
    oqpnb/anchor/<ID>          -> JSON com cada leitura
    oqpnb/anchor/<ID>/status   -> "online" / "offline"

Mostra cada leitura no terminal, um resumo periódico de RSSI por
cinto x anchor, e (opcional) grava tudo num CSV.

Requisitos:
    pip install paho-mqtt

Uso:
    python interface.py                          # broker em localhost
    python interface.py --broker 192.168.0.100   # outro PC
    python interface.py --csv leituras.csv       # grava em CSV
    python interface.py --quiet                  # só o resumo periódico

Detecção de queda (cinto_v5 + anchor_v4):
    python interface.py --modelo modelo_queda.joblib
    python interface.py --modelo modelo_queda.joblib --csv-janelas janelas.csv
  Os arquivos detector_queda.py e features.py precisam estar na mesma pasta.
  --csv-janelas grava cada janela recebida (features + probabilidade), útil
  para coletar dados do próprio cinto e retreinar o modelo depois.
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

TOPIC_BASE = "oqpnb/anchor"
FEAT_NAMES = ["amax", "amin", "astd", "gmax", "gstd", "tilt", "jerk", "post_std"]
JANELA_FIELDS = ["timestamp", "belt", "win_seq", "anchor", "prob", "queda"] + FEAT_NAMES
SENSOR_FIELDS = ["ax", "ay", "az", "gx", "gy", "gz", "bpm"]
CSV_FIELDS = (["timestamp", "anchor", "belt", "belt_num", "mac", "rssi", "seq", "anchor_ms"]
              + SENSOR_FIELDS
              + ["bpm_valid", "ecg", "leads_off", "mpu_error", "raw"])


def parse_dados(raw: str) -> dict:
    """[Formato antigo] Converte 'ax;ay;az;gx;gy;gz;bpm' em dicionário.
    Campos ausentes/truncados (o cinto corta em 22 caracteres) ficam None."""
    valores = {k: None for k in SENSOR_FIELDS}
    partes = raw.split(";") if raw else []
    # Pacote inicial do cinto contém só o ID ("OQPNB01"), sem sensores
    if len(partes) < 2:
        return valores
    for nome, texto in zip(SENSOR_FIELDS, partes):
        try:
            valores[nome] = float(texto)
        except ValueError:
            pass
    return valores


def extrair_sensores(d: dict) -> dict:
    """Retorna os campos do cinto. Usa os campos numéricos (pacote binário v2)
    se existirem; senão, cai no formato antigo de texto ('dados')."""
    if "ax" in d:
        s = {k: d.get(k) for k in SENSOR_FIELDS}
        s["bpm_valid"] = bool(d.get("bpm_valid"))
        s["ecg"] = d.get("ecg")
        s["leads_off"] = bool(d.get("leads_off"))
        s["mpu_error"] = bool(d.get("mpu_error"))
        s["seq"] = d.get("seq")
        s["belt_num"] = d.get("belt_num")
        if not s["bpm_valid"]:
            s["bpm"] = None
        return s
    s = parse_dados(d.get("dados", ""))
    s.update({"bpm_valid": None, "ecg": None, "leads_off": None,
              "mpu_error": None, "seq": None, "belt_num": None})
    return s


class Monitor:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        # (belt, anchor) -> {"rssi": [...], "last": dict, "t": time}
        self.estado = {}
        self.anchors_status = {}
        self.total = 0

        self.detector = None
        if args.modelo:
            from detector_queda import DetectorQueda
            self.detector = DetectorQueda(args.modelo, limiar=args.limiar)
            print(f"[QUEDA] Modelo carregado: {args.modelo} (limiar {self.detector.limiar:.2f})")
        self.jan_file = None
        self.jan_writer = None
        if args.csv_janelas:
            novo = not os.path.exists(args.csv_janelas) or os.path.getsize(args.csv_janelas) == 0
            self.jan_file = open(args.csv_janelas, "a", newline="", encoding="utf-8")
            self.jan_writer = csv.DictWriter(self.jan_file, fieldnames=JANELA_FIELDS)
            if novo:
                self.jan_writer.writeheader()

        self.csv_file = None
        self.csv_writer = None
        if args.csv:
            novo = not os.path.exists(args.csv) or os.path.getsize(args.csv) == 0
            self.csv_file = open(args.csv, "a", newline="", encoding="utf-8")
            self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=CSV_FIELDS)
            if novo:
                self.csv_writer.writeheader()

    # ---------------- MQTT callbacks ----------------
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            print(f"[MQTT] Falha ao conectar: {reason_code}")
            return
        print(f"[MQTT] Conectado a {self.args.broker}:{self.args.port}")
        client.subscribe(f"{TOPIC_BASE}/#", qos=0)
        print(f"[MQTT] Assinando {TOPIC_BASE}/#\n")

    def on_disconnect(self, client, userdata, *args):
        print("[MQTT] Desconectado. Tentando reconectar...")

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")

        if msg.topic.endswith("/status"):
            anchor = msg.topic.split("/")[-2]
            self.anchors_status[anchor] = payload
            print(f"[STATUS] Anchor {anchor}: {payload}")
            return

        try:
            d = json.loads(payload)
        except json.JSONDecodeError:
            print(f"[ERRO] JSON inválido em {msg.topic}: {payload}")
            return

        if d.get("type") == "feat":
            self.processar_janela(d)
            return

        agora = datetime.now()
        anchor = d.get("anchor")
        belt = d.get("belt") or d.get("mac", "?")
        rssi = d.get("rssi")
        raw = d.get("dados", "")
        sensores = extrair_sensores(d)

        with self.lock:
            self.total += 1
            chave = (belt, anchor)
            e = self.estado.setdefault(chave, {"rssi": [], "last": None, "t": 0})
            if rssi is not None:
                e["rssi"].append(rssi)
                e["rssi"] = e["rssi"][-self.args.window:]
            e["last"] = sensores
            e["t"] = time.time()

        if not self.args.quiet:
            s = sensores
            if s["ax"] is not None:
                def f(v, spec):
                    return format(v, spec) if v is not None else "?"
                bpm_txt = f"{s['bpm']:.0f}" if s["bpm"] is not None else "--"
                sens_txt = (f"A=({f(s['ax'], '+.2f')}, {f(s['ay'], '+.2f')}, {f(s['az'], '+.2f')}) g  "
                            f"G=({f(s['gx'], '+.1f')}, {f(s['gy'], '+.1f')}, {f(s['gz'], '+.1f')}) dps  "
                            f"BPM={bpm_txt}")
                if s["seq"] is not None:
                    sens_txt = f"#{s['seq']:<3} " + sens_txt
                if s["leads_off"]:
                    sens_txt += "  [ELETRODOS SOLTOS]"
                if s["mpu_error"]:
                    sens_txt += "  [ERRO MPU]"
            else:
                sens_txt = f"raw='{raw}'"
            print(f"{agora:%H:%M:%S.%f}"[:-3] +
                  f" | anchor {anchor} | {belt} | RSSI {rssi:>4} dBm | {sens_txt}")

        if self.csv_writer:
            linha = {
                "timestamp": agora.isoformat(timespec="milliseconds"),
                "anchor": anchor,
                "belt": belt,
                "mac": d.get("mac"),
                "rssi": rssi,
                "anchor_ms": d.get("ms"),
                "raw": raw,
                **sensores,
            }
            self.csv_writer.writerow(linha)
            self.csv_file.flush()

    # ---------------- Detecção de queda ----------------
    def processar_janela(self, d):
        belt = d.get("belt") or d.get("mac", "?")
        with self.lock:
            self.total += 1
            # o RSSI do pacote de janela também conta para a proximidade
            e = self.estado.setdefault((belt, d.get("anchor")), {"rssi": [], "last": None, "t": 0})
            if d.get("rssi") is not None:
                e["rssi"].append(d["rssi"])
                e["rssi"] = e["rssi"][-self.args.window:]
            e["t"] = time.time()
        if self.detector is None:
            return
        j = self.detector.processar(d)
        if j is None:          # janela repetida (outra âncora / outra cópia do anúncio)
            return
        agora = datetime.now()
        if j["queda"]:
            print("\n" + "!" * 66)
            print(f" {agora:%H:%M:%S}  QUEDA DETECTADA  {belt}  (prob {j['prob']:.2f})")
            print(f" Mais perto da âncora {j['anchor']}  |  pico {j['features']['amax']:.2f} g, "
                  f"inclinação {j['features']['tilt']:.0f} graus")
            print("!" * 66 + "\n")
        elif not self.args.quiet:
            print(f"{agora:%H:%M:%S.%f}"[:-3] + f" | janela #{j['win_seq']:<3} {belt} | "
                  f"prob queda {j['prob']:.2f} | amax {j['features']['amax']:.2f} g")
        if self.jan_writer:
            self.jan_writer.writerow({"timestamp": agora.isoformat(timespec="milliseconds"),
                                      "belt": belt, "win_seq": j["win_seq"], "anchor": j["anchor"],
                                      "prob": round(j["prob"], 4), "queda": j["queda"],
                                      **j["features"]})
            self.jan_file.flush()

    # ---------------- Resumo periódico ----------------
    def imprimir_resumo(self):
        with self.lock:
            if not self.estado:
                print("\n[RESUMO] Nenhuma leitura recebida ainda.\n")
                return
            agora = time.time()
            print("\n" + "=" * 66)
            print(f" RESUMO ({datetime.now():%H:%M:%S}) - total de mensagens: {self.total}")
            print("-" * 66)
            print(f" {'CINTO':<16}{'ANCHOR':>7}{'RSSI atual':>12}{'RSSI médio':>12}{'amostras':>10}{'idade':>8}")
            for (belt, anchor), e in sorted(self.estado.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
                r = e["rssi"]
                atual = r[-1] if r else None
                media = sum(r) / len(r) if r else None
                idade = agora - e["t"]
                print(f" {str(belt):<16}{str(anchor):>7}"
                      f"{(str(atual) + ' dBm') if atual is not None else '-':>12}"
                      f"{(f'{media:.1f} dBm') if media is not None else '-':>12}"
                      f"{len(r):>10}{idade:>7.1f}s")
            # Anchor mais próximo (maior RSSI médio) de cada cinto
            melhores = {}
            for (belt, anchor), e in self.estado.items():
                if not e["rssi"] or agora - e["t"] > 10:
                    continue
                media = sum(e["rssi"]) / len(e["rssi"])
                if belt not in melhores or media > melhores[belt][1]:
                    melhores[belt] = (anchor, media, e["last"])
            for belt, (anchor, media, last) in melhores.items():
                bpm = last.get("bpm") if last else None
                status = ""
                if last and last.get("leads_off"):
                    status = " [ELETRODOS SOLTOS]"
                bpm_txt = f"{bpm:.0f}" if bpm is not None else "--"
                print(f" -> {belt} está mais perto do anchor {anchor} ({media:.1f} dBm)"
                      f" | BPM {bpm_txt}{status}")
            if self.detector:
                for b, n in self.detector.recebidas.items():
                    print(f" -> cinto {b}: {n} janelas recebidas, "
                          f"{100 * self.detector.taxa_perda(b):.0f}% perdidas")
            print("=" * 66 + "\n")

    def fechar(self):
        if self.csv_file:
            self.csv_file.close()
        if self.jan_file:
            self.jan_file.close()


def main():
    p = argparse.ArgumentParser(description="Monitor MQTT dos anchors OQPNB")
    p.add_argument("--broker", default="localhost", help="IP/host do Mosquitto (padrão: localhost)")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--user", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--csv", default=None, help="Arquivo CSV para gravar as leituras")
    p.add_argument("--summary", type=float, default=5.0, help="Intervalo do resumo em segundos (0 = desliga)")
    p.add_argument("--window", type=int, default=20, help="Nº de amostras para a média de RSSI")
    p.add_argument("--quiet", action="store_true", help="Não imprime cada mensagem, só o resumo")
    p.add_argument("--modelo", default=None, help="Modelo de queda (.joblib) gerado pelo treino_sisfall.py")
    p.add_argument("--limiar", type=float, default=None, help="Probabilidade mínima para alarmar (padrão: a do modelo)")
    p.add_argument("--csv-janelas", default=None, help="CSV para gravar as janelas de queda recebidas")
    args = p.parse_args()

    monitor = Monitor(args)

    # Compatível com paho-mqtt 1.x e 2.x
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"interface_{os.getpid()}")
    except AttributeError:
        client = mqtt.Client(client_id=f"interface_{os.getpid()}")

    if args.user:
        client.username_pw_set(args.user, args.password)
    client.on_connect = monitor.on_connect
    client.on_disconnect = monitor.on_disconnect
    client.on_message = monitor.on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    print(f"Conectando a {args.broker}:{args.port} ...")
    try:
        client.connect(args.broker, args.port, keepalive=30)
    except OSError as e:
        print(f"Não foi possível conectar ao broker: {e}")
        print("Verifique se o Mosquitto está rodando e o IP/porta estão corretos.")
        sys.exit(1)

    client.loop_start()
    try:
        while True:
            if args.summary > 0:
                time.sleep(args.summary)
                monitor.imprimir_resumo()
            else:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        client.loop_stop()
        client.disconnect()
        monitor.fechar()


if __name__ == "__main__":
    main()

