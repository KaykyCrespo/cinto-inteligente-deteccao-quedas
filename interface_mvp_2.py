"""
interface_mvp_2.py - Terminal de Monitoramento + DETECÇÃO DE QUEDA (MVP)

Assina os tópicos MQTT publicados pela antena (anchor_mvp_v1):
    oqpnb/anchor/<ID>          -> Pacote: {cod_amb;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos;ad8232}
                                  ou, com o cinto_mvp_v2 (contador de amostra):
                                  {cod_amb;id_antena;rssi;id_cinto;seq;ax;ay;az;gx;gy;gz;eletrodos;ad8232}
    oqpnb/anchor/<ID>/status   -> "online" / "offline"

Possui duas formas de acionamento:
  1. Apenas visualizar os dados no terminal:
       python interface_mvp_1.py --view
       (ou executando `python interface_mvp_1.py` e escolhendo a opção [1])

  2. Visualizar os dados e salvar em um arquivo CSV com timestamp:
       python interface_mvp_1.py --csv leituras_mvp.csv
       (ou executando `python interface_mvp_1.py` e escolhendo a opção [2])

  3. Detecção de queda em tempo real (Random Forest treinado no SisFall):
       python interface_mvp_2.py --modelo modelos/modelo_mvp_8g.joblib --quiet
       python interface_mvp_2.py --modelo modelos/modelo_mvp_8g.joblib --quiet --csv leituras.csv --csv-janelas janelas.csv
     O cinto_mvp_v1 configura o MPU em ±8 g / ±2000 °/s, as mesmas faixas do modelo_mvp_8g.joblib.
     --quiet esconde as 100 linhas/s de amostras e mostra só janelas e alarmes.
     detector_queda.py e features.py precisam estar na mesma pasta.
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
    "seq",
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

    Modo híbrido: a antena que NÃO está conectada via GATT manda só o RSSI do anúncio,
    com os campos de sensores vazios -> {codigo_ambiente;id_antena;rssi;id_cinto;;;;;;;;}
    Nesse caso os sensores ficam None e "somente_rssi" é True.
    """
    texto = payload.strip()
    if not (texto.startswith("{") and texto.endswith("}")):
        return None

    campos = texto[1:-1].split(";")
    if len(campos) == 12:          # cinto_mvp_v1 (sem contador)
        seq = None
    elif len(campos) == 13:        # cinto_mvp_v2 (com contador de amostra)
        seq = campos.pop(4)
    else:
        return None

    def opc(txt):
        txt = txt.strip()
        return int(txt) if txt else None

    try:
        sensores = [opc(c) for c in campos[4:12]]
        d = {
            "codigo_ambiente": campos[0].strip(),
            "id_antena": int(campos[1]),
            "rssi": int(campos[2]),
            "id_cinto": int(campos[3]),
            "seq": opc(seq) if seq is not None else None,
            "ax": sensores[0], "ay": sensores[1], "az": sensores[2],
            "gx": sensores[3], "gy": sensores[4], "gz": sensores[5],
            "eletrodos_conectados": sensores[6],
            "sinal_ad8232": sensores[7],
        }
    except ValueError:
        return None
    # ou vem tudo (GATT) ou nada (só RSSI); pacote pela metade é inválido
    completo = all(v is not None for v in sensores[:6])
    vazio = all(v is None for v in sensores)
    if not (completo or vazio):
        return None
    d["somente_rssi"] = vazio
    return d


JANELA_COLUMNS = ["timestamp", "id_cinto", "id_antena", "prob", "queda",
                  "amax", "amin", "astd", "gmax", "gstd", "tilt", "jerk", "post_std"]


class MonitorMVP:
    def __init__(self, broker: str, port: int, csv_path: str | None,
                 modelo: str | None = None, limiar: float | None = None,
                 csv_janelas: str | None = None, quiet: bool = False):
        self.broker = broker
        self.port = port
        self.csv_path = csv_path
        self.quiet = quiet
        self.t_resumo = time.time()

        self.detector = None
        if modelo:
            from detector_queda import DetectorQuedaStream
            self.detector = DetectorQuedaStream(modelo, limiar=limiar)
            d = self.detector
            print(f"[QUEDA] Modelo {modelo}: {d.fs} Hz, MPU ±{d.faixa_acc:g} g / ±{d.faixa_giro:g} °/s, "
                  f"limiar {d.limiar:.2f}")
        self.jan_file = None
        self.jan_writer = None
        if csv_janelas:
            novo = not os.path.exists(csv_janelas) or os.path.getsize(csv_janelas) == 0
            self.jan_file = open(csv_janelas, mode="a", newline="", encoding="utf-8")
            self.jan_writer = csv.DictWriter(self.jan_file, fieldnames=JANELA_COLUMNS)
            if novo:
                self.jan_writer.writeheader()

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
        somente_rssi = dados.pop("somente_rssi")

        # Antena sem GATT: só RSSI do anúncio -> alimenta a localização e segue
        if somente_rssi:
            if self.detector is not None:
                self.detector.atualizar_rssi(dados["id_cinto"], dados["id_antena"], dados["rssi"])
            if self.csv_writer:
                self.csv_writer.writerow({"timestamp": ts_iso, **dados})
                self.csv_file.flush()
            if not self.quiet:
                print(f"{ts_curto} | Amb:{dados['codigo_ambiente']} | "
                      f"Ant:{dados['id_antena']} ({dados['rssi']:>4} dBm) | "
                      f"Cinto:{dados['id_cinto']} | [RSSI do anuncio, sem sensores]")
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

        # Detecção de queda
        if self.detector is not None:
            raw = (dados["ax"], dados["ay"], dados["az"], dados["gx"], dados["gy"], dados["gz"])
            j = self.detector.adicionar(dados["id_cinto"], dados["id_antena"], dados["rssi"],
                                        raw, seq=dados["seq"])
            if j is not None:
                self.mostrar_janela(j, agora)
            if t_atual - self.t_resumo >= 5.0:
                self.t_resumo = t_atual
                c = dados["id_cinto"]
                print(f"[RESUMO] {ts_curto} | cinto {c} | {self.taxa_hz:.1f} Hz | "
                      f"amostras perdidas {100 * self.detector.taxa_perda(c):.1f}% "
                      f"(só medido com o cinto_mvp_v2) | janelas reiniciadas {self.detector.resets[c]}")

        # Se estiver no modo CSV, salva a linha com o timestamp
        if self.csv_writer:
            linha = {"timestamp": ts_iso, **dados}
            self.csv_writer.writerow(linha)
            self.csv_file.flush()

        if self.quiet:
            return

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

    def mostrar_janela(self, j, agora):
        f = j["features"]
        if j["queda"]:
            print("\n" + "!" * 70)
            print(f" {agora:%H:%M:%S}  QUEDA DETECTADA  cinto {j['belt']}  (prob {j['prob']:.2f})")
            print(f" Antena com melhor sinal: {j['anchor']}  |  pico {f['amax']:.2f} g, "
                  f"inclinação {f['tilt']:.0f} graus")
            print("!" * 70 + "\n")
            try:
                import alerta_telegram as tg
            except ImportError:
                tg = None
            if tg and tg.configurado():
                rssi = self.detector.rssi[j["belt"]].get(j["anchor"]) if self.detector else None
                texto = tg.mensagem_queda(f"OQPNB{int(j['belt']):02d}", agora, j["anchor"], rssi,
                                          j["prob"], f["amax"], f["tilt"])
                tg.enviar(texto, callback=lambda ok, erro: print(
                    f"[TELEGRAM] {'alerta enviado' if ok else 'FALHOU: ' + str(erro)}"))
        elif self.quiet:
            print(f"{agora:%H:%M:%S.%f}"[:-3] + f" | janela cinto {j['belt']} | prob queda {j['prob']:.2f} | "
                  f"amax {f['amax']:.2f} g | tilt {f['tilt']:5.1f}")
        if self.jan_writer:
            self.jan_writer.writerow({"timestamp": agora.isoformat(timespec="milliseconds"),
                                      "id_cinto": j["belt"], "id_antena": j["anchor"],
                                      "prob": round(j["prob"], 4), "queda": j["queda"], **f})
            self.jan_file.flush()

    def fechar(self):
        if self.jan_file:
            self.jan_file.close()
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
    if args.modelo:
        return None

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

    parser.add_argument("--modelo", default=None, help="Modelo de queda (.joblib) para detecção em tempo real")
    parser.add_argument("--limiar", type=float, default=None, help="Probabilidade mínima para alarmar (padrão 0,5)")
    parser.add_argument("--csv-janelas", default=None, help="CSV com cada janela analisada (features + prob)")
    parser.add_argument("--quiet", action="store_true", help="Não mostra cada amostra, só janelas e alarmes")

    args = parser.parse_args()
    csv_path = selecionar_modo_acionamento(args)

    monitor = MonitorMVP(args.broker, args.port, csv_path, modelo=args.modelo, limiar=args.limiar,
                         csv_janelas=args.csv_janelas, quiet=args.quiet)

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

