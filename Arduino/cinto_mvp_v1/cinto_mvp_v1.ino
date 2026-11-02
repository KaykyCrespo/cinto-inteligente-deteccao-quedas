/*
 * ============================================================
 * CINTO MVP v1 - ESP32-C3 (BLE GATT SERVER / PERIPHERAL)
 * ============================================================
 *
 * Especificações implementadas:
 * 1. Possui Código de Ambiente (CODIGO_AMBIENTE) e ID próprio (ID_CINTO).
 * 2. Conexão GATT automática ao ligar e monitoramento contínuo de queda
 *    de conexão (reinicia o anúncio imediatamente se cair).
 * 3. Validação mútua de Código de Ambiente:
 *    - A antena envia seu CODIGO_AMBIENTE na característica de
 *      autenticação logo após conectar.
 *    - O cinto SÓ envia os pacotes de sensores se o código de ambiente
 *      da antena for idêntico ao dele.
 * 4. Lê o MPU6050 via I2C padrão (valores BRUTOS / Raw int16 dos 6 eixos).
 * 5. Lê o AD8232:
 *    - Pino 4: sinal analógico (lido SEMPRE, mesmo com eletrodos soltos).
 *    - Pino 2 (LO-) e Pino 3 (LO+): detecção de eletrodos conectados
 *      (1 = sem eletrodo solto; 0 = algum eletrodo solto).
 * 6. Envia via BLE GATT Notify o pacote no formato:
 *    {codigo_ambiente;id_cinto;seq;ax;ay;az;gx;gy;gz;eletrodos_conectados;sinal_ad8232}
 *    seq = contador 0..65535 de amostras (o PC detecta perdas e repetidas).
 *    MPU6050 em ±8 g / ±2000 °/s, valores crus (int16).
 *
 * ============================================================
 * OBSERVAÇÃO TÉCNICA SOBRE A TAXA DE LEITURA (200 Hz vs OTIMIZAÇÃO):
 * - No hardware local (I2C a 400 kHz + ADC), o ESP32 lê os sensores em ~0,5 ms,
 *   suportando 200 Hz (5 ms) facilmente.
 * - Porém, no elo completo (BLE GATT -> Antena ESP32 com rádio 2.4 GHz
 *   compartilhado entre BLE e Wi-Fi -> TCP/MQTT), o rádio da antena precisa
 *   alternar no tempo entre receber notificações BLE e transmitir pacotes Wi-Fi.
 * - Por isso, FREQ_LEITURA_HZ está configurada em 100 Hz (10 ms) como valor
 *   otimizado para máxima densidade de dados contínua com estabilidade total.
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

uint16_t seqAmostra = 0;   // contador de amostras: o PC detecta perdas e descarta repetidas

// ============================================================
// CONFIGURAÇÃO DE TAXA DE AMOSTRAGEM (Hz)
// ============================================================
// Ideal teórico: 200 Hz | Otimizado p/ BLE GATT + Wi-Fi MQTT contínuo: 100 Hz
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
// CONFIGURAÇÕES DO BLE GATT (UUIDs 16-bit p/ caber com folga nos 31B)
// ============================================================
#define SERVICE_UUID   "FFF0"
#define CHAR_AUTH_UUID "FFF1" // Write/Read: Validação do CODIGO_AMBIENTE
#define CHAR_DATA_UUID "FFF2" // Notify: Cinto envia o pacote de leituras

#define TIMEOUT_AUTENTICACAO_MS 5000 // Tempo máx p/ a antena validar o código de ambiente

NimBLEServer*         pServer   = nullptr;
NimBLECharacteristic* pAuthChar = nullptr;
NimBLECharacteristic* pDataChar = nullptr;

volatile bool     antenaConectada   = false;
volatile bool     antenaAutorizada  = false;
volatile uint16_t connHandleAntena  = BLE_HS_CONN_HANDLE_NONE;
volatile unsigned long instanteConexaoMs = 0;

unsigned long tempoAnteriorLeituraUs  = 0;
unsigned long tempoAnteriorCheckBleMs = 0;
unsigned long tempoAnteriorLogMs      = 0;
uint32_t pacotesEnviados = 0;

// ============================================================
// FUNÇÕES DO MPU6050 (Leitura Bruta / Raw dos 6 Eixos)
// ============================================================
static void escreverRegMPU(uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(reg);
  Wire.write(valor);
  Wire.endTransmission();
}

// Configuração usada no treino do modelo (modelo_mvp_8g.joblib):
//   acelerômetro ±8 g      -> 4096 LSB/g
//   giroscópio   ±2000 °/s -> 16,4 LSB/(°/s)
// Se mudar qualquer faixa aqui, o modelo precisa ser treinado de novo.
void iniciarMPU() {
  escreverRegMPU(0x6B, 0x01); // PWR_MGMT_1: acorda, clock pelo PLL do giro X
  escreverRegMPU(0x1A, 0x03); // CONFIG: filtro passa-baixa interno ~44 Hz (anti-aliasing p/ 100 Hz)
  // SMPLRT_DIV fica no padrão (1 kHz): como o loop lê por polling a 100 Hz,
  // um registrador interno mais rápido evita ler a mesma amostra duas vezes.
  // ACCEL_CONFIG: 0x00 = ±2g | 0x08 = ±4g | 0x10 = ±8g | 0x18 = ±16g
  escreverRegMPU(0x1C, 0x10); // ±8 g
  // GYRO_CONFIG: 0x00 = ±250 | 0x08 = ±500 | 0x10 = ±1000 | 0x18 = ±2000 °/s
  escreverRegMPU(0x1B, 0x18); // ±2000 °/s
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
// CALLBACKS DO SERVIDOR GATT (Conexão / Desconexão)
// ============================================================
class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* pServerInstance, NimBLEConnInfo& connInfo) override {
    connHandleAntena  = connInfo.getConnHandle();
    antenaConectada   = true;
    antenaAutorizada  = false; // Aguarda a antena provar seu CODIGO_AMBIENTE
    instanteConexaoMs = millis();

    Serial.printf("[BLE] Antena conectada (handle=%u, MAC=%s). Aguardando codigo de ambiente...\n",
                  connHandleAntena, connInfo.getAddress().toString().c_str());
  }

  void onDisconnect(NimBLEServer* pServerInstance, NimBLEConnInfo& connInfo, int reason) override {
    Serial.printf("[BLE] Conexao encerrada (motivo=%d). Reiniciando advertising...\n", reason);
    antenaConectada  = false;
    antenaAutorizada = false;
    connHandleAntena = BLE_HS_CONN_HANDLE_NONE;

    NimBLEDevice::startAdvertising();
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
// CONFIGURAÇÃO DO BLE GATT E ADVERTISING (Padrão NimBLE v2.x)
// ============================================================
void iniciarBLE() {
  char nomeDispositivo[32];
  snprintf(nomeDispositivo, sizeof(nomeDispositivo), "%s_CINTO_%02d", CODIGO_AMBIENTE, ID_CINTO);

  NimBLEDevice::init(nomeDispositivo);
  NimBLEDevice::setMTU(128);
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);

  pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(&serverCallbacks);
  pServer->advertiseOnDisconnect(true);

  NimBLEService* pService = pServer->createService(SERVICE_UUID);

  // Característica onde a Antena escreve seu CODIGO_AMBIENTE ao conectar
  pAuthChar = pService->createCharacteristic(
      CHAR_AUTH_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR,
      32
  );
  pAuthChar->setValue(CODIGO_AMBIENTE);
  pAuthChar->setCallbacks(&authCallbacks);

  // Característica onde o Cinto notifica os pacotes de sensores
  pDataChar = pService->createCharacteristic(
      CHAR_DATA_UUID,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY,
      96
  );

  pService->start();

  // Configuração limpa de Advertising + Scan Response
  NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
  pAdvertising->setName(nomeDispositivo);
  pAdvertising->addServiceUUID(pService->getUUID());

  std::string mfgData;
  mfgData += (char)0xFF;
  mfgData += (char)0xFF;
  mfgData += CODIGO_AMBIENTE;
  pAdvertising->setManufacturerData(mfgData);

  pAdvertising->enableScanResponse(true);
  pAdvertising->setMinInterval(32); // 20 ms
  pAdvertising->setMaxInterval(64); // 40 ms
  pAdvertising->start();

  Serial.printf("[BLE] Servidor GATT iniciado como '%s'. Aguardando antena...\n", nomeDispositivo);
}

// ============================================================
// VERIFICAÇÃO CONTÍNUA DO ESTADO DA CONEXÃO GATT
// ============================================================
void verificarConexaoBLE(unsigned long agoraMs) {
  // 1. Verifica se o servidor perdeu a conexão
  if (pServer && pServer->getConnectedCount() == 0) {
    if (antenaConectada) {
      antenaConectada  = false;
      antenaAutorizada = false;
      connHandleAntena = BLE_HS_CONN_HANDLE_NONE;
    }
    if (!NimBLEDevice::getAdvertising()->isAdvertising()) {
      Serial.println("[BLE] Advertising inativo detectado. Reiniciando advertising...");
      NimBLEDevice::startAdvertising();
    }
  }

  // 2. Se conectou mas a antena não validou o código de ambiente dentro do timeout, desconecta
  if (antenaConectada && !antenaAutorizada &&
      (agoraMs - instanteConexaoMs > TIMEOUT_AUTENTICACAO_MS)) {
    Serial.println("[AUTH] Timeout de autenticacao de ambiente. Desconectando cliente...");
    if (pServer && connHandleAntena != BLE_HS_CONN_HANDLE_NONE) {
      pServer->disconnect(connHandleAntena);
    }
    antenaConectada = false;
  }
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n==========================================");
  Serial.println(" CINTO MVP v1 - BLE GATT + MPU RAW + ECG");
  Serial.println("==========================================");
  Serial.printf("Codigo de Ambiente : %s\n", CODIGO_AMBIENTE);
  Serial.printf("ID do Cinto        : %d\n", ID_CINTO);
  Serial.printf("Frequencia Alvo    : %d Hz (%lu us)\n", FREQ_LEITURA_HZ, INTERVALO_LEITURA_US);

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

  // Inicializa BLE GATT Server
  iniciarBLE();
}

// ============================================================
// LOOP PRINCIPAL
// ============================================================
void loop() {
  unsigned long agoraUs = micros();
  unsigned long agoraMs = millis();

  // Checagem periódica de saúde da conexão GATT (a cada 200 ms)
  if (agoraMs - tempoAnteriorCheckBleMs >= 200) {
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

    // 4. Só envia o pacote se a antena estiver conectada E tiver o mesmo código de ambiente
    if (antenaConectada && antenaAutorizada && pDataChar != nullptr) {
      char pacote[96];
      int tam = snprintf(
          pacote, sizeof(pacote),
          "{%s;%d;%u;%d;%d;%d;%d;%d;%d;%u;%u}",
          CODIGO_AMBIENTE,
          ID_CINTO,
          (unsigned)seqAmostra++,
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
    Serial.printf("[STATUS] GATT: %s | Autorizada: %s | TX/2s: %lu (%lu Hz) | MPU: %s\n",
                  antenaConectada ? "CONECTADO" : "AGUARDANDO",
                  antenaAutorizada ? "SIM" : "NAO",
                  (unsigned long)pacotesEnviados,
                  (unsigned long)(pacotesEnviados / 2),
                  mpuOk ? "OK" : "ERRO");
    pacotesEnviados = 0;
  }
}
