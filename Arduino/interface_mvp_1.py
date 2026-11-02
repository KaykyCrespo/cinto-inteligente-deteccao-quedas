"""
interface_mvp_1.py - Terminal de Monitoramento e Validação de Sinal (MVP v1)

Assina os tópicos MQTT publicados pela antena (anchor_mvp_v1):
    oqpnb/anchor/<ID>          -> Pacote: {cod_amb;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos;ad8232}
    oqpnb/anchor/<ID>/status   -> "online" / "offline"

Possui duas formas de acionamento:
  1. Apenas visualizar os dados no terminal:
       python interface_mvp_1.py --view
       (ou executando `python interface_mvp_1.py` e escolhendo a opção [1])

  2. Visualizar os dados e salvar em um arquivo CSV com timestamp:
       python interface_mvp_1.py --csv leituras_mvp.csv
       (ou executando `python interface_mvp_1.py` e escolhendo a opção [2])
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt

TOPIC_BASE = "oqpnb/anchor"

CSV_COLUMNS = [
    "timestamp",
    "codigo_ambiente",
    "id_antena",
    "rssi",
    "id_cinto",
    "ax",
    "ay",
    "az",
    "gx",
    "gy",
    "gz",
    "eletrodos_conectados",
    "sinal_ad8232",
]


def parse_pacote_mvp(payload: str) -> dict | None:
    """
    Decodifica o pacote no formato:
    {codigo_ambiente;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
    """
    texto = payload.strip()
    if not (texto.startswith("{") and texto.endswith("}")):
        return None

    campos = texto[1:-1].split(";")
    if len(campos) != 12:
        return None

    try:
        return {
            "codigo_ambiente": campos[0].strip(),
            "id_antena": int(campos[1]),
            "rssi": int(campos[2]),
            "id_cinto": int(campos[3]),
            "ax": int(campos[4]),
            "ay": int(campos[5]),
            "az": int(campos[6]),
            "gx": int(campos[7]),
            "gy": int(campos[8]),
            "gz": int(campos[9]),
            "eletrodos_conectados": int(campos[10]),
            "sinal_ad8232": int(campos[11]),
        }
    except ValueError:
        return None


class MonitorMVP:
    def __init__(self, broker: str, port: int, csv_path: str | None):
        self.broker = broker
        self.port = port
        self.csv_path = csv_path

        self.total_mensagens = 0
        self.contador_janela = 0
        self.t_inicio_janela = time.time()
        self.taxa_hz = 0.0

        self.csv_file = None
        self.csv_writer = None

        if self.csv_path:
            arquivo_novo = not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0
            self.csv_file = open(self.csv_path, mode="a", newline="", encoding="utf-8")
            self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=CSV_COLUMNS)
            if arquivo_novo:
                self.csv_writer.writeheader()
                self.csv_file.flush()

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            print(f"[ERRO MQTT] Falha na conexão: {reason_code}")
            return
        print(f"[MQTT] Conectado a {self.broker}:{self.port}")
        client.subscribe(f"{TOPIC_BASE}/#", qos=0)
        print(f"[MQTT] Monitorando tópico '{TOPIC_BASE}/#'")
        if self.csv_path:
            print(f"[MODO 2] Visualizando e salvando leituras em: {os.path.abspath(self.csv_path)}\n")
        else:
            print("[MODO 1] Apenas visualização em tempo real (sem gravação de CSV)\n")

    def on_disconnect(self, client, userdata, *args):
        print("[MQTT] Conexão perdida. Tentando reconectar...")

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace").strip()

        # Ignora ou exibe mensagens de status online/offline da antena
        if msg.topic.endswith("/status"):
            id_antena = msg.topic.split("/")[-2]
            print(f"[STATUS ANTENA {id_antena}] {payload}")
            return

        agora = datetime.now()
        ts_iso = agora.isoformat(timespec="milliseconds")
        ts_curto = agora.strftime("%H:%M:%S.%f")[:-3]

        dados = parse_pacote_mvp(payload)
        if dados is None:
            print(f"{ts_curto} | [PACOTE INVÁLIDO] Tópico {msg.topic}: {payload}")
            return

        # Atualiza cálculo de frequência (Hz) a cada 1 segundo
        self.total_mensagens += 1
        self.contador_janela += 1
        t_atual = time.time()
        dt = t_atual - self.t_inicio_janela
        if dt >= 1.0:
            self.taxa_hz = self.contador_janela / dt
            self.contador_janela = 0
            self.t_inicio_janela = t_atual

        # Exibe no terminal para validação do sinal
        status_eletrodo = "1 (OK)" if dados["eletrodos_conectados"] == 1 else "0 (SOLTO)"
        print(
            f"{ts_curto} | Amb:{dados['codigo_ambiente']} | "
            f"Ant:{dados['id_antena']} ({dados['rssi']:>4} dBm) | "
            f"Cinto:{dados['id_cinto']} | "
            f"A_raw=({dados['ax']:>6}, {dados['ay']:>6}, {dados['az']:>6}) | "
            f"G_raw=({dados['gx']:>6}, {dados['gy']:>6}, {dados['gz']:>6}) | "
            f"Eletrodos:{status_eletrodo} | "
            f"AD8232:{dados['sinal_ad8232']:>4} | "
            f"{self.taxa_hz:>5.1f} Hz"
        )

        # Se estiver no modo CSV, salva a linha com o timestamp
        if self.csv_writer:
            linha = {"timestamp": ts_iso, **dados}
            self.csv_writer.writerow(linha)
            self.csv_file.flush()

    def fechar(self):
        if self.csv_file:
            self.csv_file.close()
            print(f"\n[CSV] Arquivo salvo com sucesso em: {os.path.abspath(self.csv_path)}")


def selecionar_modo_acionamento(args) -> str | None:
    """
    Define qual das duas formas de acionamento será usada:
      - Retorna None se for apenas para visualizar.
      - Retorna o caminho do arquivo CSV se for para visualizar e salvar.
    """
    if args.view:
        return None
    if args.csv:
        return args.csv

    # Se nenhum argumento de modo foi passado na linha de comando, pergunta no terminal
    print("=" * 60)
    print(" INTERFACE DE VALIDAÇÃO MVP v1")
    print("=" * 60)
    print("Selecione a forma de acionamento:")
    print("  [1] Apenas visualizar os dados no terminal")
    print("  [2] Visualizar e salvar os dados em um CSV com timestamp")
    print("-" * 60)
    escolha = input("Digite 1 ou 2 [padrão=1]: ").strip()

    if escolha == "2":
        nome_padrao = f"leituras_mvp_{datetime.now():%Y%m%d_%H%M%S}.csv"
        caminho = input(f"Nome do arquivo CSV [padrão={nome_padrao}]: ").strip()
        return caminho if caminho else nome_padrao

    return None


def main():
    parser = argparse.ArgumentParser(description="Terminal de Validação MVP v1 (MQTT)")
    parser.add_argument("--broker", default="localhost", help="IP/host do broker Mosquitto (padrão: localhost)")
    parser.add_argument("--port", type=int, default=1883, help="Porta do broker MQTT (padrão: 1883)")
    parser.add_argument("--user", default=None, help="Usuário MQTT (opcional)")
    parser.add_argument("--password", default=None, help="Senha MQTT (opcional)")

    grupo_modo = parser.add_mutually_exclusive_group()
    grupo_modo.add_argument(
        "--view",
        action="store_true",
        help="Forma 1: Apenas visualizar os dados no terminal",
    )
    grupo_modo.add_argument(
        "--csv",
        nargs="?",
        const="leituras_mvp.csv",
        default=None,
        help="Forma 2: Visualizar e salvar os dados em CSV com timestamp (padrão: leituras_mvp.csv)",
    )

    args = parser.parse_args()
    csv_path = selecionar_modo_acionamento(args)

    monitor = MonitorMVP(args.broker, args.port, csv_path)

    # Compatível com paho-mqtt 1.x e 2.x
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"interface_mvp1_{os.getpid()}")
    except AttributeError:
        client = mqtt.Client(client_id=f"interface_mvp1_{os.getpid()}")

    if args.user:
        client.username_pw_set(args.user, args.password)

    client.on_connect = monitor.on_connect
    client.on_disconnect = monitor.on_disconnect
    client.on_message = monitor.on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    print(f"\nConectando ao broker MQTT em {args.broker}:{args.port} ...")
    try:
        client.connect(args.broker, args.port, keepalive=30)
    except OSError as e:
        print(f"[ERRO] Não foi possível conectar ao broker MQTT: {e}")
        sys.exit(1)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nEncerrando monitoramento...")
    finally:
        client.disconnect()
        monitor.fechar()


if __name__ == "__main__":
    main()

