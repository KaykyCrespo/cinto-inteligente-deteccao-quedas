/*
 * ============================================================
 * ANCHOR (ANTENA) MVP v1 - ESP32 (MODO HÍBRIDO: GATT + SCAN RSSI)
 * ============================================================
 *
 * Arquitetura Híbrida implementada:
 * 1. Possui Código de Ambiente (CODIGO_AMBIENTE) e ID próprio (ID_ANTENA).
 * 2. Filtra SOMENTE dispositivos Bluetooth do projeto que possuírem o
 *    mesmo CODIGO_AMBIENTE (no anúncio `{CODIGO_AMBIENTE;ID_CINTO}` e nos
 *    pacotes GATT).
 * 3. Operação em Modo Conectado GATT (Antena principal do fluxo rápido):
 *    - Quando o anúncio do cinto está CONECTÁVEL (cinto sem antena GATT),
 *      a antena conecta automaticamente via GATT, valida seu CODIGO_AMBIENTE
 *      e recebe o fluxo de alta frequência (100 Hz) com sensores + RSSI:
 *      {codigo_ambiente;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
 * 4. Operação em Modo Scanner RSSI (Demais antenas da sala ou enquanto sem GATT):
 *    - Quando a antena NÃO está conectada via GATT ao cinto, ela escuta os
 *      anúncios `{CODIGO_AMBIENTE;ID_CINTO}` do cinto, calcula o RSSI e
 *      envia via MQTT o pacote com os campos de sensores vazios:
 *      {codigo_ambiente;id_antena;rssi;id_cinto;;;;;;;;}
 *    - Se a conexão GATT da outra antena cair, o cinto volta a anunciar como
 *      conectável e uma antena disponível assume a conexão GATT automaticamente.
 * ============================================================
 */

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <WiFi.h>
#include <PubSubClient.h>

// ============================================================
// IDENTIFICAÇÃO E AMBIENTE (EDITAR AQUI)
// ============================================================
#define CODIGO_AMBIENTE "OQPNB"
#define ID_ANTENA       4

// ============================================================
// CONFIGURAÇÕES DE WI-FI E MQTT (EDITAR AQUI)
// ============================================================
#define WIFI_SSID       "NOME_DO_SEU_WIFI"
#define WIFI_PASSWORD   "SENHA_DO_SEU_WIFI"

#define MQTT_BROKER     "10.106.177.139" //.46 enzo .82 kayky
#define MQTT_PORT       1883
#define MQTT_USER       ""
#define MQTT_PASS       ""
#define MQTT_TOPIC_BASE "oqpnb/anchor"

// ============================================================
// UUIDs DO SERVIÇO E CARACTERÍSTICAS GATT (Iguais aos do Cinto)
// ============================================================
#define SERVICE_UUID   "FFF0"
#define CHAR_AUTH_UUID "FFF1" // Write/Read: Antena envia seu CODIGO_AMBIENTE
#define CHAR_DATA_UUID "FFF2" // Notify: Recebe pacotes do Cinto

// ============================================================
// ESTRUTURA DA FILA FREERTOS (BLE GATT / Scan -> Loop MQTT)
// ============================================================
struct ItemFila {
  int  rssi;
  // Quando conectado GATT : "id_cinto;ax;ay;az;gx;gy;gz;eletrodos;ad8232}"
  // Quando só anúncio RSSI: "id_cinto;;;;;;;;}"
  char restoDadosCinto[80];
};

QueueHandle_t filaPacotes;

// ============================================================
// VARIÁVEIS DE ESTADO BLE GATT E MQTT
// ============================================================
NimBLEClient*  pClient      = nullptr;
NimBLEScan*    pBLEScan     = nullptr;
NimBLEAddress  enderecoAlvo;

volatile bool deveConectar   = false;
volatile bool conectadoGATT  = false;
volatile int  rssiAtual      = -70;

WiFiClient   espClient;
PubSubClient mqtt(espClient);

char topicoDados[48];
char topicoStatus[56];

// Contadores e temporizadores
volatile uint32_t pacotesRecebidosGATT  = 0;
volatile uint32_t pacotesRecebidosAdv   = 0;
volatile uint32_t pacotesPerdidosFila   = 0;
uint32_t          pacotesPublicadosMQTT = 0;

unsigned long tempoAnteriorStatusMs      = 0;
unsigned long tempoUltimaTentativaWiFiMs = 0;
unsigned long tempoUltimaTentativaMqttMs = 0;
unsigned long tempoUltimaChecagemBleMs   = 0;
unsigned long tempoUltimaTentativaConnMs = 0;

// ============================================================
// EXTRAÇÃO E VALIDAÇÃO DE AMBIENTE NO ANÚNCIO DO CINTO
// ============================================================
// Verifica se o anúncio pertence ao mesmo CODIGO_AMBIENTE e extrai o ID_CINTO.
// O cinto anuncia no Manufacturer Data: [0xFF, 0xFF] + "{CODIGO_AMBIENTE;ID_CINTO}"
bool extrairIdCintoDoAnuncio(const NimBLEAdvertisedDevice* dev, int* idCintoOut) {
  size_t tamAmb = strlen(CODIGO_AMBIENTE);

  // 1. Tenta extrair do Manufacturer Data: [0xFF, 0xFF] + "{OQPNB;1}"
  if (dev->haveManufacturerData()) {
    std::string mfg = dev->getManufacturerData();
    if (mfg.length() >= 2 + 1 + tamAmb + 2) {
      const char* payload = mfg.c_str() + 2; // Pula os 2 bytes do Company ID (0xFFFF)
      if (payload[0] == '{' &&
          strncmp(payload + 1, CODIGO_AMBIENTE, tamAmb) == 0 &&
          payload[1 + tamAmb] == ';') {
        int idLido = atoi(payload + 1 + tamAmb + 1);
        if (idLido > 0) {
          *idCintoOut = idLido;
          return true;
        }
      }
    }
  }

  // 2. Fallback: tenta extrair do Nome do dispositivo ("OQPNB_CINTO_01")
  std::string nome = dev->getName();
  std::string prefixo = std::string(CODIGO_AMBIENTE) + "_CINTO_";
  if (nome.rfind(prefixo, 0) == 0) {
    int idLido = atoi(nome.c_str() + prefixo.length());
    if (idLido > 0) {
      *idCintoOut = idLido;
      return true;
    }
  }

  return false;
}

// ============================================================
// CALLBACK DE NOTIFICAÇÃO GATT (Fluxo rápido com sensores)
// ============================================================
void callbackNotificacaoGATT(NimBLERemoteCharacteristic* pBLERemoteCharacteristic,
                             uint8_t* pData,
                             size_t length,
                             bool isNotify) {
  if (length == 0 || length >= 95) return;

  char buffer[96];
  memcpy(buffer, pData, length);
  buffer[length] = '\0';

  // Formato esperado do cinto via GATT:
  // {codigo_ambiente;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
  size_t tamCodigo = strlen(CODIGO_AMBIENTE);

  if (buffer[0] != '{' ||
      strncmp(buffer + 1, CODIGO_AMBIENTE, tamCodigo) != 0 ||
      buffer[1 + tamCodigo] != ';' ||
      buffer[length - 1] != '}') {
    return; // Descarta pacotes que não possuam o mesmo código de ambiente
  }

  pacotesRecebidosGATT++;

  ItemFila item;
  item.rssi = rssiAtual;
  strncpy(item.restoDadosCinto, buffer + 1 + tamCodigo + 1, sizeof(item.restoDadosCinto) - 1);
  item.restoDadosCinto[sizeof(item.restoDadosCinto) - 1] = '\0';

  if (xQueueSend(filaPacotes, &item, 0) != pdTRUE) {
    pacotesPerdidosFila++;
  }
}

// ============================================================
// CALLBACKS DO CLIENTE GATT (Conexão / Desconexão)
// ============================================================
class ClientCallbacks : public NimBLEClientCallbacks {
  void onConnect(NimBLEClient* pClientInstance) override {
    Serial.printf("[GATT] Link fisico estabelecido com %s.\n",
                  pClientInstance->getPeerAddress().toString().c_str());
  }

  void onDisconnect(NimBLEClient* pClientInstance, int reason) override {
    conectadoGATT = false;
    deveConectar  = false;
    Serial.printf("[GATT] Conexao com o cinto caiu (motivo=%d). Voltando ao modo Scanner RSSI + Reconexao...\n", reason);
  }
} clientCallbacks;

// ============================================================
// CALLBACK DO SCANNER BLE (Envia RSSI do anúncio e detecta GATT livre)
// ============================================================
class ScanCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* advertisedDevice) override {
    // Se esta antena já está conectada via GATT ao cinto, o RSSI + sensores já vêm pelo GATT
    if (conectadoGATT) return;

    int idCinto = 0;
    if (!extrairIdCintoDoAnuncio(advertisedDevice, &idCinto)) {
      return; // Ignora dispositivos que não têm o mesmo CODIGO_AMBIENTE
    }

    int rssiAnuncio = advertisedDevice->getRSSI();
    rssiAtual = rssiAnuncio;
    pacotesRecebidosAdv++;

    // 1. Enfileira pacote de RSSI com variáveis de sensores vazias:
    //    Resultado final no MQTT: {codigo_ambiente;id_antena;rssi;id_cinto;;;;;;;;}
    ItemFila item;
    item.rssi = rssiAnuncio;
    snprintf(item.restoDadosCinto, sizeof(item.restoDadosCinto), "%d;;;;;;;;}", idCinto);

    if (xQueueSend(filaPacotes, &item, 0) != pdTRUE) {
      pacotesPerdidosFila++;
    }

    // 2. Se o anúncio do cinto for CONECTÁVEL (ou seja, o cinto está sem antena GATT),
    //    agenda a conexão GATT automática para que esta antena receba o fluxo de sensores.
    if (advertisedDevice->isConnectable() && !deveConectar) {
      Serial.printf("[SCAN] Cinto %d (%s) disponivel para GATT (RSSI=%d dBm). Agendando conexao...\n",
                    idCinto,
                    advertisedDevice->getAddress().toString().c_str(),
                    rssiAnuncio);
      enderecoAlvo = advertisedDevice->getAddress();
      deveConectar = true;
    }
  }

  void onScanEnd(const NimBLEScanResults& results, int reason) override {
    if (!conectadoGATT && !deveConectar) {
      NimBLEDevice::getScan()->start(0, false, true);
    }
  }
} scanCallbacks;

// ============================================================
// FUNÇÕES DE SCAN E CONEXÃO GATT AUTOMÁTICA
// ============================================================
void iniciarScanBLE() {
  if (conectadoGATT || deveConectar) return;
  if (pBLEScan && !pBLEScan->isScanning()) {
    pBLEScan->start(0, false, true);
  }
}

void limparClienteBLE() {
  if (pClient != nullptr) {
    if (pClient->isConnected()) {
      pClient->disconnect();
    }
    NimBLEDevice::deleteClient(pClient);
    pClient = nullptr;
  }
  conectadoGATT = false;
}

bool conectarAoCinto() {
  if (pBLEScan && pBLEScan->isScanning()) {
    pBLEScan->stop();
    delay(20);
  }

  limparClienteBLE();

  Serial.printf("[GATT] Tentando conectar ao cinto %s...\n", enderecoAlvo.toString().c_str());

  pClient = NimBLEDevice::createClient();
  pClient->setClientCallbacks(&clientCallbacks, false);
  pClient->setConnectionParams(12, 12, 0, 200, 64, 32);
  pClient->setConnectTimeout(3000);

  if (!pClient->connect(enderecoAlvo)) {
    Serial.println("[GATT] Nao conectou (outra antena pode ter assumido). Mantendo envio de RSSI via anuncio...");
    limparClienteBLE();
    return false;
  }

  NimBLERemoteService* pService = pClient->getService(SERVICE_UUID);
  if (pService == nullptr) {
    Serial.println("[GATT] Servico GATT FFF0 nao encontrado. Desconectando...");
    limparClienteBLE();
    return false;
  }

  // 1. Envia o CODIGO_AMBIENTE da antena para autenticar junto ao cinto
  NimBLERemoteCharacteristic* pAuthChar = pService->getCharacteristic(CHAR_AUTH_UUID);
  if (pAuthChar == nullptr) {
    Serial.println("[GATT] Caracteristica FFF1 nao encontrada. Desconectando...");
    limparClienteBLE();
    return false;
  }

  bool authOk = pAuthChar->writeValue((const uint8_t*)CODIGO_AMBIENTE, strlen(CODIGO_AMBIENTE), false);
  if (!authOk) {
    authOk = pAuthChar->writeValue((const uint8_t*)CODIGO_AMBIENTE, strlen(CODIGO_AMBIENTE), true);
  }
  if (!authOk) {
    Serial.println("[GATT] Falha ao enviar codigo de ambiente. Desconectando...");
    limparClienteBLE();
    return false;
  }

  // 2. Inscreve-se na característica de dados (Notify)
  NimBLERemoteCharacteristic* pDataChar = pService->getCharacteristic(CHAR_DATA_UUID);
  if (pDataChar == nullptr || !pDataChar->canNotify()) {
    Serial.println("[GATT] Caracteristica FFF2 invalida. Desconectando...");
    limparClienteBLE();
    return false;
  }

  if (!pDataChar->subscribe(true, callbackNotificacaoGATT)) {
    Serial.println("[GATT] Falha ao assinar notificacoes GATT. Desconectando...");
    limparClienteBLE();
    return false;
  }

  conectadoGATT = true;
  int rssiLido = pClient->getRssi();
  if (rssiLido != 0) rssiAtual = rssiLido;

  Serial.printf("[GATT] CONECTADO E AUTENTICADO! Recebendo fluxo de 100 Hz + RSSI (%d dBm)...\n", rssiAtual);
  return true;
}

// ============================================================
// GERENCIAMENTO DE WI-FI E MQTT (Não Bloqueante)
// ============================================================
void manterWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - tempoUltimaTentativaWiFiMs < 10000) return;
  tempoUltimaTentativaWiFiMs = millis();

  Serial.println("[WIFI] Desconectado. Tentando conectar...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void manterMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqtt.connected()) return;
  if (millis() - tempoUltimaTentativaMqttMs < 3000) return;
  tempoUltimaTentativaMqttMs = millis();

  char clientId[32];
  snprintf(clientId, sizeof(clientId), "anchor_mvp_%d", ID_ANTENA);

  Serial.printf("[MQTT] Conectando ao broker %s:%d... ", MQTT_BROKER, MQTT_PORT);

  bool ok;
  if (strlen(MQTT_USER) > 0) {
    ok = mqtt.connect(clientId, MQTT_USER, MQTT_PASS, topicoStatus, 1, true, "offline");
  } else {
    ok = mqtt.connect(clientId, topicoStatus, 1, true, "offline");
  }

  if (ok) {
    Serial.println("OK!");
    mqtt.publish(topicoStatus, "online", true);
  } else {
    Serial.printf("Falhou (rc=%d)\n", mqtt.state());
  }
}

// ============================================================
// PROCESSAMENTO DA FILA E REPASSE VIA MQTT
// ============================================================
void processarFilaMQTT() {
  ItemFila item;
  while (xQueueReceive(filaPacotes, &item, 0) == pdTRUE) {
    // Formato com GATT conectado:
    //   {codigo_ambiente;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
    // Formato sem GATT conectado (apenas RSSI do anúncio):
    //   {codigo_ambiente;id_antena;rssi;id_cinto;;;;;;;;}
    char pacoteFinal[128];
    snprintf(
        pacoteFinal, sizeof(pacoteFinal),
        "{%s;%d;%d;%s",
        CODIGO_AMBIENTE,
        ID_ANTENA,
        item.rssi,
        item.restoDadosCinto // Já termina com "}"
    );

    if (mqtt.connected()) {
      if (mqtt.publish(topicoDados, pacoteFinal)) {
        pacotesPublicadosMQTT++;
      }
    }
  }
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  snprintf(topicoDados, sizeof(topicoDados), "%s/%d", MQTT_TOPIC_BASE, ID_ANTENA);
  snprintf(topicoStatus, sizeof(topicoStatus), "%s/%d/status", MQTT_TOPIC_BASE, ID_ANTENA);

  Serial.println("\n==================================================");
  Serial.println(" ANCHOR (ANTENA) MVP v1 - HIBRIDO (GATT + RSSI)");
  Serial.println("==================================================");
  Serial.printf("Codigo de Ambiente : %s\n", CODIGO_AMBIENTE);
  Serial.printf("ID da Antena       : %d\n", ID_ANTENA);
  Serial.printf("Topico MQTT        : %s\n\n", topicoDados);

  filaPacotes = xQueueCreate(64, sizeof(ItemFila));

  // Inicializa Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  tempoUltimaTentativaWiFiMs = millis();

  Serial.print("[WIFI] Conectando ao Wi-Fi");
  unsigned long inicioWifi = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicioWifi < 4000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  // Inicializa MQTT
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setBufferSize(256);
  mqtt.setKeepAlive(15);

  // Inicializa BLE GATT Client + Scanner
  NimBLEDevice::init("");
  NimBLEDevice::setMTU(128);

  pBLEScan = NimBLEDevice::getScan();
  // true = recebe todos os anúncios continuamente p/ cálculo de RSSI em tempo real
  pBLEScan->setScanCallbacks(&scanCallbacks, true);
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(70);
  pBLEScan->setMaxResults(0);

  iniciarScanBLE();
}

// ============================================================
// LOOP PRINCIPAL
// ============================================================
void loop() {
  unsigned long agoraMs = millis();

  // 1. Mantém conexões Wi-Fi e MQTT ativas
  manterWiFi();
  manterMQTT();
  mqtt.loop();

  // 2. Se o cinto está disponível para conexão GATT, tenta conectar
  //    (usa pequeno escalonamento por ID_ANTENA p/ evitar colisão entre antenas)
  unsigned long intervaloTentativaMs = 600 + ((ID_ANTENA % 5) * 150);
  if (deveConectar && (agoraMs - tempoUltimaTentativaConnMs >= intervaloTentativaMs)) {
    deveConectar = false;
    tempoUltimaTentativaConnMs = agoraMs;
    if (!conectarAoCinto()) {
      iniciarScanBLE();
    }
  }

  // 3. Checagem contínua se a conexão GATT caiu ou se deve manter o scanner de RSSI ativo
  if (agoraMs - tempoUltimaChecagemBleMs >= 250) {
    tempoUltimaChecagemBleMs = agoraMs;

    if (conectadoGATT) {
      if (pClient == nullptr || !pClient->isConnected()) {
        Serial.println("[GATT] Queda de conexao detectada. Retomando Scanner RSSI + Reconexao...");
        limparClienteBLE();
        iniciarScanBLE();
      } else {
        // Atualiza o RSSI da conexão GATT ativa em relação ao cinto
        int novoRssi = pClient->getRssi();
        if (novoRssi != 0) {
          rssiAtual = novoRssi;
        }
      }
    } else if (!deveConectar) {
      // Enquanto não conectado via GATT, garante que o scanner está sempre ouvindo os anúncios
      iniciarScanBLE();
    }
  }

  // 4. Repassa todos os pacotes (sejam GATT completos ou apenas RSSI) para o MQTT
  processarFilaMQTT();

  // 5. Resumo periódico no Serial (a cada 5 s)
  if (agoraMs - tempoAnteriorStatusMs >= 5000) {
    tempoAnteriorStatusMs = agoraMs;
    Serial.printf("[STATUS] Modo: %s (RSSI %d dBm) | RX GATT: %lu | RX Adv(RSSI): %lu | TX MQTT: %lu | WiFi: %s | MQTT: %s\n",
                  conectadoGATT ? "GATT+SENSORES" : "SCAN_RSSI",
                  rssiAtual,
                  (unsigned long)pacotesRecebidosGATT,
                  (unsigned long)pacotesRecebidosAdv,
                  (unsigned long)pacotesPublicadosMQTT,
                  WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "OFF",
                  mqtt.connected() ? "ON" : "OFF");

    pacotesRecebidosGATT  = 0;
    pacotesRecebidosAdv   = 0;
    pacotesPublicadosMQTT = 0;
    pacotesPerdidosFila   = 0;
  }
}
