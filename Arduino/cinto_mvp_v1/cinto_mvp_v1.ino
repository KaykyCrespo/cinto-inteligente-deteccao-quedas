/*
 * ============================================================
 * CINTO MVP v1 - ESP32-C3 (MODO HÍBRIDO: GATT + BEACON DE RSSI)
 * ============================================================
 *
 * Arquitetura Híbrida implementada:
 * 1. Anúncio BLE Estático (Advertising):
 *    - Envia APENAS {codigo_ambiente;id_cinto} no Manufacturer Data.
 *    - Nunca precisa ser reescrito com dados de sensores (zero sobrecarga).
 *    - Quando o cinto está SEM conexão GATT: anuncia em modo CONECTÁVEL
 *      (BLE_GAP_CONN_MODE_UND) para que uma antena disponível conecte.
 *    - Quando o cinto JÁ ESTÁ conectado via GATT a uma antena: continua
 *      anunciando em modo NÃO-CONECTÁVEL (BLE_GAP_CONN_MODE_NON) a cada
 *      100 ms para que TODAS as outras antenas da sala meçam e enviem o RSSI!
 * 2. Conexão GATT de Alta Velocidade (100 Hz):
 *    - Exclusiva para enviar o fluxo rápido de sensores para a antena conectada:
 *      {codigo_ambiente;id_cinto;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
 *    - Só envia se a antena conectada tiver validado o mesmo CODIGO_AMBIENTE.
 *    - Se a conexão GATT cair, volta imediatamente o anúncio para modo
 *      CONECTÁVEL para reconectar automaticamente a uma antena disponível.
 * ============================================================
 */

#include <Arduino.h>
#include <Wire.h>
#include <NimBLEDevice.h>

// ============================================================
// IDENTIFICAÇÃO E AMBIENTE
// ============================================================
#define CODIGO_AMBIENTE "OQPNB"
#define ID_CINTO        1

// ============================================================
// CONFIGURAÇÃO DE TAXA DE AMOSTRAGEM GATT (Hz)
// ============================================================
#define FREQ_LEITURA_HZ 100
const unsigned long INTERVALO_LEITURA_US = 1000000UL / FREQ_LEITURA_HZ;

// ============================================================
// PINOS DO AD8232 (ECG) E LED DE STATUS
// ============================================================
#define PINO_LOM          2   // AD8232 LO-
#define PINO_LOP          3   // AD8232 LO+
#define PINO_SINAL_AD8232 4   // Entrada analógica do AD8232
#define PINO_LED          10  // LED indicador (aceso = eletrodo solto)

// ============================================================
// CONFIGURAÇÕES DO MPU6050 (I2C Padrão)
// ============================================================
#define MPU_ADDRESS 0x68

int16_t rawAX = 0, rawAY = 0, rawAZ = 0;
int16_t rawGX = 0, rawGY = 0, rawGZ = 0;
bool    mpuOk = false;

// ============================================================
// CONFIGURAÇÕES DO BLE GATT (UUIDs 16-bit)
// ============================================================
#define SERVICE_UUID   "FFF0"
#define CHAR_AUTH_UUID "FFF1" // Write/Read: Validação do CODIGO_AMBIENTE
#define CHAR_DATA_UUID "FFF2" // Notify: Cinto envia o pacote de leituras

#define TIMEOUT_AUTENTICACAO_MS 5000 // Tempo máx p/ a antena validar o código de ambiente

NimBLEServer*         pServer   = nullptr;
NimBLECharacteristic* pAuthChar = nullptr;
NimBLECharacteristic* pDataChar = nullptr;

volatile bool     antenaConectada       = false;
volatile bool     antenaAutorizada      = false;
volatile bool     atualizarModoAnuncio  = false;
volatile uint16_t connHandleAntena      = BLE_HS_CONN_HANDLE_NONE;
volatile unsigned long instanteConexaoMs = 0;

unsigned long tempoAnteriorLeituraUs  = 0;
unsigned long tempoAnteriorCheckBleMs = 0;
unsigned long tempoAnteriorLogMs      = 0;
uint32_t pacotesEnviados = 0;

// ============================================================
// FUNÇÕES DO MPU6050 (Leitura Bruta / Raw dos 6 Eixos)
// ============================================================
void iniciarMPU() {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x6B); // Registrador PWR_MGMT_1
  Wire.write(0x00); // Acorda o MPU6050
  Wire.endTransmission();

  // Configura acelerômetro para ±8g:
  // 0x00 = ±2g | 0x08 = ±4g | 0x10 = ±8g | 0x18 = ±16g
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x1C); // Registrador ACCEL_CONFIG
  Wire.write(0x10); // Seleciona ±8g
  Wire.endTransmission();

  // Configura giroscópio para ±2000 °/s:
  // 0x00 = ±250 | 0x08 = ±500 | 0x10 = ±1000 | 0x18 = ±2000
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x1B); // Registrador GYRO_CONFIG
  Wire.write(0x18); // Seleciona ±2000 °/s
  Wire.endTransmission();
}

void lerMPUBruto() {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x3B); // Registrador inicial (ACCEL_XOUT_H)
  if (Wire.endTransmission(false) != 0) {
    mpuOk = false;
    rawAX = rawAY = rawAZ = 0;
    rawGX = rawGY = rawGZ = 0;
    iniciarMPU(); // Tenta reinicializar caso tenha reconectado
    return;
  }

  // Solicita 14 bytes: 6 Acel + 2 Temp + 6 Giro
  uint8_t lidos = Wire.requestFrom((uint8_t)MPU_ADDRESS, (uint8_t)14, (uint8_t)true);
  if (lidos == 14) {
    rawAX = (int16_t)((Wire.read() << 8) | Wire.read());
    rawAY = (int16_t)((Wire.read() << 8) | Wire.read());
    rawAZ = (int16_t)((Wire.read() << 8) | Wire.read());

    // Descarta os 2 bytes de temperatura (0x41 e 0x42)
    Wire.read();
    Wire.read();

    rawGX = (int16_t)((Wire.read() << 8) | Wire.read());
    rawGY = (int16_t)((Wire.read() << 8) | Wire.read());
    rawGZ = (int16_t)((Wire.read() << 8) | Wire.read());
    mpuOk = true;
  } else {
    mpuOk = false;
    while (Wire.available()) Wire.read();
  }
}

// ============================================================
// CONTROLE DO ANÚNCIO HÍBRIDO (Conectável vs Beacon de RSSI)
// ============================================================
// O pacote de anúncio contém SEMPRE apenas {CODIGO_AMBIENTE;ID_CINTO}.
// - conectavel = true  -> permite que uma antena disponível conecte via GATT.
// - conectavel = false -> mantém o anúncio ativo em modo NÃO-CONECTÁVEL
//                         enquanto o GATT está conectado, para que as demais
//                         antenas calculem o RSSI sem disputar a conexão GATT.
void configurarAnuncioHibrido(bool conectavel) {
  NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
  if (pAdvertising->isAdvertising()) {
    pAdvertising->stop();
  }

  if (conectavel) {
    pAdvertising->setConnectableMode(BLE_GAP_CONN_MODE_UND);
    pAdvertising->setDiscoverableMode(BLE_GAP_DISC_MODE_GEN);
    pAdvertising->setMinInterval(32);  // 20 ms (reconexão GATT rápida)
    pAdvertising->setMaxInterval(64);  // 40 ms
  } else {
    pAdvertising->setConnectableMode(BLE_GAP_CONN_MODE_NON);
    pAdvertising->setDiscoverableMode(BLE_GAP_DISC_MODE_GEN);
    pAdvertising->setMinInterval(160); // 100 ms (beacon leve p/ RSSI nas outras antenas)
    pAdvertising->setMaxInterval(160); // 100 ms
  }

  pAdvertising->refreshAdvertisingData();
  pAdvertising->start();

  Serial.printf("[ADV] Anuncio estatico {%s;%d} ativo em modo %s.\n",
                CODIGO_AMBIENTE, ID_CINTO,
                conectavel ? "CONECTAVEL (buscando antena GATT)" : "BEACON RSSI (GATT ja conectado)");
}

// ============================================================
// CALLBACKS DO SERVIDOR GATT (Conexão / Desconexão)
// ============================================================
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* pServerInstance, NimBLEConnInfo& connInfo) override {
    connHandleAntena     = connInfo.getConnHandle();
    antenaConectada      = true;
    antenaAutorizada     = false; // Aguarda a antena provar seu CODIGO_AMBIENTE
    instanteConexaoMs    = millis();
    atualizarModoAnuncio = true;  // Liga o beacon não-conectável p/ as demais antenas

    Serial.printf("[BLE] Antena conectada (handle=%u, MAC=%s). Aguardando codigo de ambiente...\n",
                  connHandleAntena, connInfo.getAddress().toString().c_str());
  }

  void onDisconnect(NimBLEServer* pServerInstance, NimBLEConnInfo& connInfo, int reason) override {
    Serial.printf("[BLE] Conexao GATT caiu (motivo=%d). Voltando anuncio para modo CONECTAVEL...\n", reason);
    antenaConectada      = false;
    antenaAutorizada     = false;
    connHandleAntena     = BLE_HS_CONN_HANDLE_NONE;
    atualizarModoAnuncio = true;  // Volta a aceitar conexão GATT de qualquer antena disponível
  }
} serverCallbacks;

// ============================================================
// CALLBACK DE AUTENTICAÇÃO DO CÓDIGO DE AMBIENTE DA ANTENA
// ============================================================
class AuthCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
    std::string codigoRecebido = pCharacteristic->getValue();

    // Remove possíveis quebras de linha, espaços ou byte nulo final
    while (!codigoRecebido.empty() &&
           (codigoRecebido.back() == '\0' || codigoRecebido.back() == '\r' ||
            codigoRecebido.back() == '\n' || codigoRecebido.back() == ' ')) {
      codigoRecebido.pop_back();
    }

    if (codigoRecebido == CODIGO_AMBIENTE) {
      antenaAutorizada = true;
      Serial.printf("[AUTH] Antena autorizada! Codigo de ambiente '%s' validado.\n",
                    codigoRecebido.c_str());
    } else {
      antenaAutorizada = false;
      Serial.printf("[AUTH] REJEITADO! Codigo da antena ('%s') difere do cinto ('%s'). Desconectando...\n",
                    codigoRecebido.c_str(), CODIGO_AMBIENTE);
      if (pServer) {
        pServer->disconnect(connInfo.getConnHandle());
      }
    }
  }
} authCallbacks;

// ============================================================
// CONFIGURAÇÃO DO BLE GATT E ADVERTISING HÍBRIDO
// ============================================================
void iniciarBLE() {
  char nomeDispositivo[32];
  snprintf(nomeDispositivo, sizeof(nomeDispositivo), "%s_CINTO_%02d", CODIGO_AMBIENTE, ID_CINTO);

  NimBLEDevice::init(nomeDispositivo);
  NimBLEDevice::setMTU(128);
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);

  pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(&serverCallbacks);
  // Gerenciamos o reinício do anúncio manualmente para alternar entre Conectável e Beacon
  pServer->advertiseOnDisconnect(false);

  NimBLEService* pService = pServer->createService(SERVICE_UUID);

  // Característica onde a Antena escreve seu CODIGO_AMBIENTE ao conectar
  pAuthChar = pService->createCharacteristic(
      CHAR_AUTH_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR,
      32
  );
  pAuthChar->setValue(CODIGO_AMBIENTE);
  pAuthChar->setCallbacks(&authCallbacks);

  // Característica onde o Cinto notifica os pacotes de sensores em alta frequência
  pDataChar = pService->createCharacteristic(
      CHAR_DATA_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY,
      96
  );

  pService->start();

  // Monta o payload estático do anúncio: Company ID (0xFFFF) + "{CODIGO_AMBIENTE;ID_CINTO}"
  char idPayload[24];
  snprintf(idPayload, sizeof(idPayload), "{%s;%d}", CODIGO_AMBIENTE, ID_CINTO);

  std::string mfgData;
  mfgData += (char)0xFF;
  mfgData += (char)0xFF;
  mfgData += idPayload;

  NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
  pAdvertising->setName(nomeDispositivo);
  pAdvertising->addServiceUUID(pService->getUUID());
  pAdvertising->setManufacturerData(mfgData);
  pAdvertising->enableScanResponse(true);

  // Inicia em modo CONECTÁVEL para buscar uma antena disponível
  configurarAnuncioHibrido(true);
}

// ============================================================
// VERIFICAÇÃO CONTÍNUA DO ESTADO DA CONEXÃO E DO ANÚNCIO
// ============================================================
void verificarConexaoBLE(unsigned long agoraMs) {
  // 1. Atualiza o modo do anúncio sempre que conectar ou desconectar
  if (atualizarModoAnuncio) {
    atualizarModoAnuncio = false;
    configurarAnuncioHibrido(!antenaConectada);
  }

  // 2. Verifica se a conexão GATT caiu sem disparar callback
  if (pServer && pServer->getConnectedCount() == 0 && antenaConectada) {
    antenaConectada  = false;
    antenaAutorizada = false;
    connHandleAntena = BLE_HS_CONN_HANDLE_NONE;
    configurarAnuncioHibrido(true);
  }

  // 3. Garante que o rádio está SEMPRE anunciando (seja em modo conectável ou beacon de RSSI)
  if (!NimBLEDevice::getAdvertising()->isAdvertising()) {
    configurarAnuncioHibrido(!antenaConectada);
  }

  // 4. Se conectou mas a antena não validou o código de ambiente dentro do timeout, desconecta
  if (antenaConectada && !antenaAutorizada &&
      (agoraMs - instanteConexaoMs > TIMEOUT_AUTENTICACAO_MS)) {
    Serial.println("[AUTH] Timeout de autenticacao de ambiente. Desconectando cliente...");
    if (pServer && connHandleAntena != BLE_HS_CONN_HANDLE_NONE) {
      pServer->disconnect(connHandleAntena);
    }
    antenaConectada = false;
    configurarAnuncioHibrido(true);
  }
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n==================================================");
  Serial.println(" CINTO MVP v1 - HIBRIDO (GATT 100Hz + BEACON RSSI)");
  Serial.println("==================================================");
  Serial.printf("Codigo de Ambiente : %s\n", CODIGO_AMBIENTE);
  Serial.printf("ID do Cinto        : %d\n", ID_CINTO);
  Serial.printf("Frequencia GATT    : %d Hz (%lu us)\n", FREQ_LEITURA_HZ, INTERVALO_LEITURA_US);

  // Inicializa I2C a 400 kHz (Fast Mode) com timeout curto para nunca travar
  Wire.begin();
  Wire.setClock(400000);
  Wire.setTimeOut(50);
  iniciarMPU();

  // Configura pinos do AD8232
  pinMode(PINO_LOM, INPUT);
  pinMode(PINO_LOP, INPUT);
  pinMode(PINO_LED, OUTPUT);
  analogReadResolution(12);

  // Inicializa BLE GATT Server + Anúncio Híbrido
  iniciarBLE();
}

// ============================================================
// LOOP PRINCIPAL
// ============================================================
void loop() {
  unsigned long agoraUs = micros();
  unsigned long agoraMs = millis();

  // Checagem periódica de saúde da conexão GATT e do Anúncio (a cada 100 ms)
  if (agoraMs - tempoAnteriorCheckBleMs >= 100) {
    tempoAnteriorCheckBleMs = agoraMs;
    verificarConexaoBLE(agoraMs);
  }

  // Leitura dos sensores e envio GATT na frequência configurada
  if (agoraUs - tempoAnteriorLeituraUs >= INTERVALO_LEITURA_US) {
    tempoAnteriorLeituraUs += INTERVALO_LEITURA_US;
    if (agoraUs - tempoAnteriorLeituraUs > 10 * INTERVALO_LEITURA_US) {
      tempoAnteriorLeituraUs = agoraUs; // Ressincroniza se houve atraso
    }

    // 1. Lê valores brutos (Raw) dos 6 eixos do MPU6050
    lerMPUBruto();

    // 2. Lê estado dos eletrodos (pinos 2 e 3)
    //    1 = nenhum eletrodo solto (conectados) | 0 = algum eletrodo solto
    bool eletrodoSolto = (digitalRead(PINO_LOP) == HIGH) || (digitalRead(PINO_LOM) == HIGH);
    uint8_t eletrodosConectados = eletrodoSolto ? 0 : 1;
    digitalWrite(PINO_LED, eletrodoSolto ? HIGH : LOW);

    // 3. Lê o sinal analógico no pino 4 SEMPRE (mesmo se eletrodo estiver desconectado)
    uint16_t sinalAnalogico = analogRead(PINO_SINAL_AD8232);

    // 4. Só envia o fluxo rápido de sensores via GATT se a antena estiver conectada E autorizada
    if (antenaConectada && antenaAutorizada && pDataChar != nullptr) {
      char pacote[96];
      int tam = snprintf(
          pacote, sizeof(pacote),
          "{%s;%d;%d;%d;%d;%d;%d;%d;%u;%u}",
          CODIGO_AMBIENTE,
          ID_CINTO,
          rawAX, rawAY, rawAZ,
          rawGX, rawGY, rawGZ,
          eletrodosConectados,
          sinalAnalogico
      );

      if (tam > 0 && tam < (int)sizeof(pacote)) {
        if (pDataChar->notify((const uint8_t*)pacote, (size_t)tam)) {
          pacotesEnviados++;
        }
      }
    }
  }

  // Resumo de diagnóstico no Serial a cada 2 segundos
  if (agoraMs - tempoAnteriorLogMs >= 2000) {
    tempoAnteriorLogMs = agoraMs;
    Serial.printf("[STATUS] GATT: %s | Autorizada: %s | Adv: %s | TX GATT/2s: %lu (%lu Hz) | MPU: %s\n",
                  antenaConectada ? "CONECTADO" : "AGUARDANDO",
                  antenaAutorizada ? "SIM" : "NAO",
                  NimBLEDevice::getAdvertising()->isAdvertising() ? "ATIVO" : "PARADO",
                  (unsigned long)pacotesEnviados,
                  (unsigned long)(pacotesEnviados / 2),
                  mpuOk ? "OK" : "ERRO");
    pacotesEnviados = 0;
  }
}
