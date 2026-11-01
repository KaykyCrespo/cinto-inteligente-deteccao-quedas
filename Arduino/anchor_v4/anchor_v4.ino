/*
 * ============================================================
 * ANCHOR - ESP32
 * BLE SCANNER (Versão NimBLE Otimizada - v2.5.1+) + MQTT
 * Escuta TODOS os dispositivos BLE da sala, mas só processa os
 * que contêm o código "OQPNB" (no nome ou nos dados).
 * Envia: dados do cinto + número do anchor + RSSI -> Mosquitto
 * ============================================================
 *
 * Tópicos MQTT publicados:
 *   oqpnb/anchor/<ANCHOR_ID>          -> JSON com cada leitura
 *   oqpnb/anchor/<ANCHOR_ID>/status   -> "online" / "offline" (retido)
 *
 * Exemplo de JSON (cinto com pacote binário v2):
 *   {"anchor":1,"belt":"CINTO_OQPNB01","belt_num":1,"mac":"aa:bb:cc:dd:ee:ff",
 *    "rssi":-62,"seq":17,"ax":0.012,"ay":-0.034,"az":0.998,
 *    "gx":-1.2,"gy":0.4,"gz":0.0,"bpm":72,"bpm_valid":true,"ecg":2051,
 *    "leads_off":false,"mpu_error":false,"ms":123456}
 *   ax/ay/az em g, gx/gy/gz em graus/s, bpm = batimentos por minuto.
 *
 * v4: também repassa o pacote de janela do cinto_v5 (versão 3, detecção de queda):
 *   {"anchor":1,"belt":"CINTO_OQPNB01","belt_num":1,"mac":"...","rssi":-62,
 *    "type":"feat","win_seq":17,"feat":[1012,950,31,120,40,210,25,9],"ms":123456}
 *   feat = 8 int16 na ordem amax amin astd gmax gstd tilt jerk post_std.
 *   O Random Forest roda no PC (interface.py + detector_queda.py).
 *
 *   Cada "seq" pode chegar mais de uma vez (o cinto repete o anúncio a
 *   cada 100 ms e atualiza a cada 250 ms) -> mais amostras de RSSI.
 */

#include <Arduino.h>
#include <NimBLEDevice.h> 
#include <WiFi.h>
#include <PubSubClient.h>

// ============================================================
// CONFIGURAÇÕES (EDITAR AQUI)
// ============================================================
#define ANCHOR_ID 4                  // Número deste anchor (1, 2, 3...)

#define WIFI_SSID     "NOME_DO_SEU_WIFI"
#define WIFI_PASSWORD "SENHA_DO_SEU_WIFI"

#define MQTT_BROKER   "10.1.0.156"  // IP do PC com o Mosquitto
#define MQTT_PORT     1883
#define MQTT_USER     ""               // Deixe "" se o broker não usa login
#define MQTT_PASS     ""
#define MQTT_TOPIC_BASE "oqpnb/anchor"

#define FILTER_CODE "OQPNB"     // Código de 5 letras a filtrar
#define STATUS_INTERVAL 5000    // Intervalo do resumo no Serial (ms)

// ============================================================
// ESTRUTURA DE LEITURA (passada do callback BLE para o loop)
// ============================================================
// O callback BLE roda na task do NimBLE: não se deve publicar MQTT
// de lá. Por isso as leituras vão para uma fila e o loop() publica.
struct Leitura {
  char nome[32];
  char mac[18];
  int  rssi;
  uint32_t ms;

  bool    binario;      // true = pacote v2 decodificado
  bool    janela;       // true = pacote v3 (features de queda)
  uint8_t winSeq;
  int16_t feat[8];
  // --- campos do pacote binário v2 (ver cinto_v3) ---
  uint8_t beltNum;
  uint8_t seq;
  int16_t ax, ay, az;   // mili-g
  int16_t gx, gy, gz;   // 0.1 dps
  uint8_t bpm;
  uint8_t flags;
  uint16_t ecg;
  // --- fallback: formato texto antigo ---
  char dados[32];
};

// Formato binário enviado pelo cinto (após o Company ID 0xFFFF)
#define PROTO_VERSION 2
#define PROTO_FEAT    3
struct __attribute__((packed)) PacoteCinto {
  char     magic[5];
  uint8_t  versao;
  uint8_t  beltNum;
  uint8_t  seq;
  int16_t  ax, ay, az;
  int16_t  gx, gy, gz;
  uint8_t  bpm;
  uint8_t  flags;
  uint16_t ecg;
};
static_assert(sizeof(PacoteCinto) == 24, "PacoteCinto precisa ter 24 bytes");

#define FLAG_ELETRODO_SOLTO 0x01
#define FLAG_ERRO_MPU       0x02
#define FLAG_BPM_VALIDO     0x04

QueueHandle_t filaLeituras;
NimBLEScan *pBLEScan;

WiFiClient espClient;
PubSubClient mqtt(espClient);

char topicoDados[48];
char topicoStatus[56];

// Contadores
volatile uint32_t totalPacotes = 0;   // todos os anúncios ouvidos
volatile uint32_t pacotesFiltro = 0;  // anúncios que contêm OQPNB
volatile uint32_t pacotesPerdidos = 0;// fila cheia
uint32_t pacotesEnviados = 0;         // publicados no MQTT
unsigned long tempo_anterior_status = 0;
unsigned long tempo_ultima_tentativa_wifi = 0;
unsigned long tempo_ultima_tentativa_mqtt = 0;

// Copia só caracteres imprimíveis e seguros para JSON
static void copiarSeguro(char *dst, size_t tam, const std::string &src, size_t inicio = 0) {
  size_t j = 0;
  for (size_t i = inicio; i < src.length() && j < tam - 1; i++) {
    char c = src[i];
    if (c >= 32 && c <= 126 && c != '"' && c != '\\') dst[j++] = c;
  }
  dst[j] = '\0';
}

// ============================================================
// CALLBACK DE DISPOSITIVO ENCONTRADO
// ============================================================
// Na v2.0+, a classe base chama-se NimBLEScanCallbacks
class MyAdvertisedDeviceCallbacks : public NimBLEScanCallbacks {

  // É obrigatório adicionar "const" antes do ponteiro na v2.0+
  void onResult(const NimBLEAdvertisedDevice* advertisedDevice) override {
    totalPacotes++;

    std::string nome    = advertisedDevice->getName();
    std::string mfgData = advertisedDevice->haveManufacturerData()
                            ? advertisedDevice->getManufacturerData()
                            : std::string();

    // Filtro: o código precisa aparecer no nome OU nos manufacturer data
    bool temCodigo = (nome.find(FILTER_CODE) != std::string::npos) ||
                     (mfgData.find(FILTER_CODE) != std::string::npos);
    if (!temCodigo) {
      return; // Ignora silenciosamente todos os outros dispositivos
    }
    pacotesFiltro++;

    Leitura l;
    memset(&l, 0, sizeof(l));
    copiarSeguro(l.nome, sizeof(l.nome), nome);
    copiarSeguro(l.mac, sizeof(l.mac), advertisedDevice->getAddress().toString());
    l.rssi = advertisedDevice->getRSSI();
    l.ms   = millis();

    // Pacote binário v2: [0xFF 0xFF] + 24 bytes começando com "OQPNB"
    if (mfgData.length() >= 2 + sizeof(PacoteCinto) &&
        memcmp(mfgData.data() + 2, "OQPNB", 5) == 0 &&
        (uint8_t)mfgData[2 + 5] == PROTO_VERSION) {
      PacoteCinto p;
      memcpy(&p, mfgData.data() + 2, sizeof(p));
      l.binario = true;
      l.beltNum = p.beltNum;
      l.seq = p.seq;
      l.ax = p.ax; l.ay = p.ay; l.az = p.az;
      l.gx = p.gx; l.gy = p.gy; l.gz = p.gz;
      l.bpm = p.bpm;
      l.flags = p.flags;
      l.ecg = p.ecg;
      // Se o scan response (nome) não chegou, monta o nome pelo número
      if (l.nome[0] == '\0') {
        snprintf(l.nome, sizeof(l.nome), "CINTO_OQPNB%02u", p.beltNum);
      }
    } else if (mfgData.length() >= 2 + 24 &&
               memcmp(mfgData.data() + 2, "OQPNB", 5) == 0 &&
               (uint8_t)mfgData[2 + 5] == PROTO_FEAT) {
      // Pacote de janela v3: [magic 5][versao][beltNum][winSeq][8 x int16 LE]
      const uint8_t *b = (const uint8_t *)mfgData.data() + 2;
      l.janela = true;
      l.beltNum = b[6];
      l.winSeq = b[7];
      for (int i = 0; i < 8; i++) {
        l.feat[i] = (int16_t)(b[8 + 2 * i] | (b[8 + 2 * i + 1] << 8));
      }
      if (l.nome[0] == '\0') {
        snprintf(l.nome, sizeof(l.nome), "CINTO_OQPNB%02u", l.beltNum);
      }
    } else {
      // Formato antigo (texto). Ignora os 2 primeiros bytes (Company ID)
      copiarSeguro(l.dados, sizeof(l.dados), mfgData, mfgData.length() > 2 ? 2 : mfgData.length());
    }

    if (xQueueSend(filaLeituras, &l, 0) != pdTRUE) {
      pacotesPerdidos++;
    }
  }

  // Se o scan parar por qualquer motivo, reinicia
  void onScanEnd(const NimBLEScanResults& results, int reason) override {
    NimBLEDevice::getScan()->start(0, false, true);
  }
};

// ============================================================
// WIFI / MQTT (reconexão não bloqueante)
// ============================================================
void manterWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - tempo_ultima_tentativa_wifi < 10000) return;
  tempo_ultima_tentativa_wifi = millis();

  Serial.println("WiFi desconectado. Tentando conectar...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void manterMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) return;
  if (millis() - tempo_ultima_tentativa_mqtt < 3000) return;
  tempo_ultima_tentativa_mqtt = millis();

  char clientId[24];
  snprintf(clientId, sizeof(clientId), "anchor_%d", ANCHOR_ID);

  Serial.print("Conectando ao MQTT ");
  Serial.print(MQTT_BROKER);
  Serial.print("... ");

  // Last Will: se o anchor cair, o broker publica "offline"
  bool ok;
  if (strlen(MQTT_USER) > 0) {
    ok = mqtt.connect(clientId, MQTT_USER, MQTT_PASS, topicoStatus, 1, true, "offline");
  } else {
    ok = mqtt.connect(clientId, topicoStatus, 1, true, "offline");
  }

  if (ok) {
    Serial.println("OK");
    mqtt.publish(topicoStatus, "online", true);
  } else {
    Serial.print("falhou, rc=");
    Serial.println(mqtt.state());
  }
}

// ============================================================
// PUBLICAR LEITURAS DA FILA
// ============================================================
void processarFila() {
  Leitura l;
  while (xQueueReceive(filaLeituras, &l, 0) == pdTRUE) {
    char json[400];
    if (l.janela) {
      snprintf(json, sizeof(json),
               "{\"anchor\":%d,\"belt\":\"%s\",\"belt_num\":%u,\"mac\":\"%s\",\"rssi\":%d,"
               "\"type\":\"feat\",\"win_seq\":%u,\"feat\":[%d,%d,%d,%d,%d,%d,%d,%d],\"ms\":%lu}",
               ANCHOR_ID, l.nome, l.beltNum, l.mac, l.rssi, l.winSeq,
               l.feat[0], l.feat[1], l.feat[2], l.feat[3],
               l.feat[4], l.feat[5], l.feat[6], l.feat[7],
               (unsigned long)l.ms);
    } else if (l.binario) {
      bool soltos = l.flags & FLAG_ELETRODO_SOLTO;
      bool errMpu = l.flags & FLAG_ERRO_MPU;
      bool bpmOk  = l.flags & FLAG_BPM_VALIDO;
      snprintf(json, sizeof(json),
               "{\"anchor\":%d,\"belt\":\"%s\",\"belt_num\":%u,\"mac\":\"%s\",\"rssi\":%d,"
               "\"seq\":%u,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,"
               "\"gx\":%.1f,\"gy\":%.1f,\"gz\":%.1f,"
               "\"bpm\":%u,\"bpm_valid\":%s,\"ecg\":%u,"
               "\"leads_off\":%s,\"mpu_error\":%s,\"ms\":%lu}",
               ANCHOR_ID, l.nome, l.beltNum, l.mac, l.rssi,
               l.seq, l.ax / 1000.0, l.ay / 1000.0, l.az / 1000.0,
               l.gx / 10.0, l.gy / 10.0, l.gz / 10.0,
               l.bpm, bpmOk ? "true" : "false", l.ecg,
               soltos ? "true" : "false", errMpu ? "true" : "false",
               (unsigned long)l.ms);

      Serial.printf("BLE RX [%s | %d dBm] #%u A=(%.2f, %.2f, %.2f)g G=(%.1f, %.1f, %.1f)dps BPM=%u%s%s\n",
                    l.nome, l.rssi, l.seq,
                    l.ax / 1000.0, l.ay / 1000.0, l.az / 1000.0,
                    l.gx / 10.0, l.gy / 10.0, l.gz / 10.0,
                    l.bpm, bpmOk ? "" : "(--)",
                    soltos ? " [ELETRODOS SOLTOS]" : "");
    } else {
      snprintf(json, sizeof(json),
               "{\"anchor\":%d,\"belt\":\"%s\",\"mac\":\"%s\",\"rssi\":%d,\"dados\":\"%s\",\"ms\":%lu}",
               ANCHOR_ID, l.nome, l.mac, l.rssi, l.dados, (unsigned long)l.ms);

      Serial.printf("BLE RX [%s | %d dBm] (formato antigo) %s\n",
                    l.nome[0] ? l.nome : "(sem nome)", l.rssi, l.dados);
    }

    if (mqtt.connected()) {
      if (mqtt.publish(topicoDados, json)) pacotesEnviados++;
    }
  }
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  snprintf(topicoDados, sizeof(topicoDados), "%s/%d", MQTT_TOPIC_BASE, ANCHOR_ID);
  snprintf(topicoStatus, sizeof(topicoStatus), "%s/%d/status", MQTT_TOPIC_BASE, ANCHOR_ID);

  Serial.println("\n=================================");
  Serial.print("ANCHOR ");
  Serial.print(ANCHOR_ID);
  Serial.println(" - BLE SCANNER + MQTT");
  Serial.println("=================================");

  Serial.print("Filtrando dispositivos com o codigo: ");
  Serial.println(FILTER_CODE);
  Serial.print("Topico MQTT: ");
  Serial.println(topicoDados);
  Serial.println();

  filaLeituras = xQueueCreate(40, sizeof(Leitura));

  // --- WiFi ---
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  tempo_ultima_tentativa_wifi = millis();

  // --- MQTT ---
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(15);

  // --- BLE ---
  NimBLEDevice::init("");
  pBLEScan = NimBLEDevice::getScan();
  
  // true = recebe duplicados (cada novo anúncio do cinto gera um callback,
  // assim os dados dos sensores e o RSSI chegam atualizados continuamente)
  pBLEScan->setScanCallbacks(new MyAdvertisedDeviceCallbacks(), true);
  
  // Scan ATIVO é obrigatório: o nome "CINTO_OQPNB01" vem no scan response
  pBLEScan->setActiveScan(true);
  // Janela < intervalo: deixa tempo de rádio livre para o WiFi (rádio compartilhado)
  pBLEScan->setInterval(100); 
  pBLEScan->setWindow(80);    
  pBLEScan->setMaxResults(0); // Não guarda lista (evita encher a memória)

  // Duração 0 = scan contínuo (não bloqueia o loop)
  pBLEScan->start(0, false, true);

  Serial.println("Scanner iniciado.");
  Serial.println();
}

// ============================================================
// LOOP
// ============================================================
void loop() {
  manterWiFi();
  manterMQTT();
  mqtt.loop();

  processarFila();

  // Resumo periódico
  if (millis() - tempo_anterior_status >= STATUS_INTERVAL) {
    tempo_anterior_status = millis();
    Serial.print("-> BLE ouvidos: ");
    Serial.print(totalPacotes);
    Serial.print(" | com ");
    Serial.print(FILTER_CODE);
    Serial.print(": ");
    Serial.print(pacotesFiltro);
    Serial.print(" | MQTT enviados: ");
    Serial.print(pacotesEnviados);
    Serial.print(" | perdidos: ");
    Serial.print(pacotesPerdidos);
    Serial.print(" | WiFi: ");
    Serial.print(WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String("OFF"));
    Serial.print(" | MQTT: ");
    Serial.println(mqtt.connected() ? "ON" : "OFF");
    totalPacotes = 0;
    pacotesFiltro = 0;
    pacotesEnviados = 0;
    pacotesPerdidos = 0;
  }

  // Segurança: se por algum motivo o scan parou, reinicia
  if (!pBLEScan->isScanning()) {
    pBLEScan->start(0, false, true);
  }
  delay(5);
}