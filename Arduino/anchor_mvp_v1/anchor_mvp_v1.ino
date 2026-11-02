/*
 * ============================================================
 * ANCHOR (ANTENA) MVP v1 - ESP32 (BLE GATT CLIENT + MQTT)
 * ============================================================
 *
 * Especificações implementadas:
 * 1. Possui Código de Ambiente (CODIGO_AMBIENTE) e ID próprio (ID_ANTENA).
 * 2. Conexão GATT automática ao ligar e verificação contínua de queda
 *    de conexão (retoma a busca e reconecta automaticamente se cair).
 * 3. Filtra e recebe informações SOMENTE de dispositivos Bluetooth que
 *    possuírem o mesmo Código de Ambiente (no anúncio BLE e na validação
 *    de cada pacote recebido via GATT).
 * 4. Envia seu CODIGO_AMBIENTE ao cinto logo após conectar via GATT para
 *    que o cinto também autorize o envio dos pacotes.
 * 5. Mede o RSSI em relação ao cinto conectado e repassa cada pacote
 *    adicionando seu ID_ANTENA e o RSSI via MQTT no formato exato:
 *    {codigo_ambiente;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
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
#define ID_ANTENA       1

// ============================================================
// CONFIGURAÇÕES DE WI-FI E MQTT (EDITAR AQUI)
// ============================================================
#define WIFI_SSID       "NOME_DO_SEU_WIFI"
#define WIFI_PASSWORD   "SENHA_DO_SEU_WIFI"

#define MQTT_BROKER     "192.168.15.145" //.42 enzo .145 kayky
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
// ESTRUTURA DA FILA FREERTOS (Callback BLE -> Loop MQTT)
// ============================================================
struct ItemFila {
  int  rssi;
  char restoDadosCinto[80]; // Contém: "id_cinto;ax;ay;az;gx;gy;gz;eletrodos;ad8232}"
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
volatile uint32_t pacotesRejeitadosAmb  = 0;
volatile uint32_t pacotesPerdidosFila   = 0;
uint32_t          pacotesPublicadosMQTT = 0;

unsigned long tempoAnteriorStatusMs      = 0;
unsigned long tempoUltimaTentativaWiFiMs = 0;
unsigned long tempoUltimaTentativaMqttMs = 0;
unsigned long tempoUltimaChecagemBleMs   = 0;
unsigned long tempoUltimaTentativaConnMs = 0;

// ============================================================
// CALLBACK DE NOTIFICAÇÃO GATT (Recebe pacote do Cinto)
// ============================================================
void callbackNotificacaoGATT(NimBLERemoteCharacteristic* pBLERemoteCharacteristic,
                             uint8_t* pData,
                             size_t length,
                             bool isNotify) {
  if (length == 0 || length >= 95) return;

  char buffer[96];
  memcpy(buffer, pData, length);
  buffer[length] = '\0';

  // Formato esperado do cinto:
  // {codigo_ambiente;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
  size_t tamCodigo = strlen(CODIGO_AMBIENTE);

  // Valida se começa com "{<CODIGO_AMBIENTE>;" e termina com "}"
  if (buffer[0] != '{' ||
      strncmp(buffer + 1, CODIGO_AMBIENTE, tamCodigo) != 0 ||
      buffer[1 + tamCodigo] != ';' ||
      buffer[length - 1] != '}') {
    pacotesRejeitadosAmb++;
    return; // Descarta pacotes que não possuam o mesmo código de ambiente
  }

  pacotesRecebidosGATT++;

  // Extrai o sufixo após "{<CODIGO_AMBIENTE>;" -> "id_cinto;ax;ay;az;gx;gy;gz;eletrodos;ad8232}"
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
    Serial.printf("[GATT] Conexao com o cinto caiu (motivo=%d). Retomando busca...\n", reason);
  }
} clientCallbacks;

// ============================================================
// CALLBACK DO SCANNER BLE (Filtra pelo Código de Ambiente)
// ============================================================
class ScanCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* advertisedDevice) override {
    if (conectadoGATT || deveConectar) return;

    // Ignora anúncios não-conectáveis (ex: versões antigas sem servidor GATT)
    if (!advertisedDevice->isConnectable()) return;

    std::string nome    = advertisedDevice->getName();
    std::string mfgData = advertisedDevice->haveManufacturerData()
                            ? advertisedDevice->getManufacturerData()
                            : std::string();

    // Verifica se o dispositivo possui o mesmo CODIGO_AMBIENTE (no nome ou no Manufacturer Data)
    bool mesmoAmbiente = (nome.find(CODIGO_AMBIENTE) != std::string::npos) ||
                         (mfgData.find(CODIGO_AMBIENTE) != std::string::npos);

    if (!mesmoAmbiente) {
      return; // Ignora dispositivos de outros ambientes
    }

    Serial.printf("[SCAN] Cinto do ambiente '%s' encontrado: %s (MAC=%s, RSSI=%d dBm)\n",
                  CODIGO_AMBIENTE,
                  nome.empty() ? "(sem nome)" : nome.c_str(),
                  advertisedDevice->getAddress().toString().c_str(),
                  advertisedDevice->getRSSI());

    enderecoAlvo = advertisedDevice->getAddress();
    rssiAtual    = advertisedDevice->getRSSI();
    deveConectar = true;
    // OBS: Não chamamos stop() dentro do callback para evitar conflito na task NimBLE;
    // o stop() é chamado com segurança no loop() antes de conectar.
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
    Serial.printf("[SCAN] Procurando cinto conectavel com codigo '%s'...\n", CODIGO_AMBIENTE);
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
  // Para o scanner com segurança fora do callback antes de iniciar a conexão GATT
  if (pBLEScan && pBLEScan->isScanning()) {
    pBLEScan->stop();
    delay(20);
  }

  // Garante um cliente limpo no estado DISCONNECTED
  limparClienteBLE();

  Serial.printf("[GATT] Conectando ao cinto %s...\n", enderecoAlvo.toString().c_str());

  pClient = NimBLEDevice::createClient();
  pClient->setClientCallbacks(&clientCallbacks, false);

  // Parâmetros compatíveis com coexistência Wi-Fi + BLE (scanWindow=32 < scanInterval=64)
  // Intervalo de conexão: 12 * 1.25ms = 15ms | Timeout supervisão: 200 * 10ms = 2000ms
  pClient->setConnectionParams(12, 12, 0, 200, 64, 32);
  pClient->setConnectTimeout(5000);

  if (!pClient->connect(enderecoAlvo)) {
    Serial.println("[GATT] Falha ao estabelecer conexao fisica. Tentando novamente em breve...");
    limparClienteBLE();
    return false;
  }

  // Localiza o serviço GATT do cinto
  NimBLERemoteService* pService = pClient->getService(SERVICE_UUID);
  if (pService == nullptr) {
    Serial.println("[GATT] Servico GATT FFF0 nao encontrado no cinto. Desconectando...");
    limparClienteBLE();
    return false;
  }

  // 1. Envia o CODIGO_AMBIENTE da antena para autenticar junto ao cinto
  NimBLERemoteCharacteristic* pAuthChar = pService->getCharacteristic(CHAR_AUTH_UUID);
  if (pAuthChar == nullptr) {
    Serial.println("[GATT] Caracteristica de autenticacao FFF1 nao encontrada. Desconectando...");
    limparClienteBLE();
    return false;
  }

  // Escreve o código de ambiente (tenta sem resposta para menor latência, ou com resposta como fallback)
  bool authOk = pAuthChar->writeValue((const uint8_t*)CODIGO_AMBIENTE, strlen(CODIGO_AMBIENTE), false);
  if (!authOk) {
    authOk = pAuthChar->writeValue((const uint8_t*)CODIGO_AMBIENTE, strlen(CODIGO_AMBIENTE), true);
  }
  if (!authOk) {
    Serial.println("[GATT] Falha ao enviar codigo de ambiente ao cinto. Desconectando...");
    limparClienteBLE();
    return false;
  }
  Serial.printf("[GATT] Codigo de ambiente '%s' enviado ao cinto!\n", CODIGO_AMBIENTE);

  // 2. Inscreve-se na característica de dados (Notify)
  NimBLERemoteCharacteristic* pDataChar = pService->getCharacteristic(CHAR_DATA_UUID);
  if (pDataChar == nullptr || !pDataChar->canNotify()) {
    Serial.println("[GATT] Caracteristica de dados FFF2 invalida. Desconectando...");
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

  Serial.printf("[GATT] CONECTADO E AUTENTICADO! Recebendo pacotes (RSSI=%d dBm)...\n", rssiAtual);
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
    // Monta o pacote repassado adicionando ID_ANTENA e RSSI:
    // {codigo_ambiente;id_antena;rssi;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
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

  Serial.println("\n==========================================");
  Serial.println(" ANCHOR (ANTENA) MVP v1 - GATT + MQTT");
  Serial.println("==========================================");
  Serial.printf("Codigo de Ambiente : %s\n", CODIGO_AMBIENTE);
  Serial.printf("ID da Antena       : %d\n", ID_ANTENA);
  Serial.printf("Topico MQTT        : %s\n\n", topicoDados);

  filaPacotes = xQueueCreate(64, sizeof(ItemFila));

  // Inicializa Wi-Fi e aguarda até 4s pela primeira associação para não
  // disputar o rádio 2.4 GHz exatamente no instante do handshake BLE GATT
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
  // true = aceita duplicados para nunca travar a redescoberta caso precise reconectar
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

  // 2. Se o scanner encontrou o cinto do mesmo ambiente, realiza a conexão GATT
  if (deveConectar && (agoraMs - tempoUltimaTentativaConnMs >= 500)) {
    deveConectar = false;
    tempoUltimaTentativaConnMs = agoraMs;
    if (!conectarAoCinto()) {
      iniciarScanBLE();
    }
  }

  // 3. Checagem contínua se a conexão GATT caiu ou não
  if (agoraMs - tempoUltimaChecagemBleMs >= 250) {
    tempoUltimaChecagemBleMs = agoraMs;

    if (conectadoGATT) {
      if (pClient == nullptr || !pClient->isConnected()) {
        Serial.println("[GATT] Queda de conexao detectada na checagem ativa. Reconectando...");
        limparClienteBLE();
        iniciarScanBLE();
      } else {
        // Atualiza o RSSI da conexão ativa em relação ao cinto
        int novoRssi = pClient->getRssi();
        if (novoRssi != 0) {
          rssiAtual = novoRssi;
        }
      }
    } else if (!deveConectar) {
      // Se não está conectado nem conectando, garante que o scanner está rodando
      iniciarScanBLE();
    }
  }

  // 4. Repassa todos os pacotes recebidos na fila para o MQTT
  processarFilaMQTT();

  // 5. Resumo periódico no Serial (a cada 5 s)
  if (agoraMs - tempoAnteriorStatusMs >= 5000) {
    tempoAnteriorStatusMs = agoraMs;
    Serial.printf("[STATUS] GATT: %s (RSSI %d dBm) | RX GATT: %lu | TX MQTT: %lu | Perdidos: %lu | WiFi: %s | MQTT: %s\n",
                  conectadoGATT ? "CONECTADO" : "BUSCANDO",
                  rssiAtual,
                  (unsigned long)pacotesRecebidosGATT,
                  (unsigned long)pacotesPublicadosMQTT,
                  (unsigned long)pacotesPerdidosFila,
                  WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "OFF",
                  mqtt.connected() ? "ON" : "OFF");

    pacotesRecebidosGATT  = 0;
    pacotesPublicadosMQTT = 0;
    pacotesPerdidosFila   = 0;
  }
}
