/*
 * ============================================================
 * CINTO - ESP32-C3
 * LEITURA SEGURA DIRETA + ECG (BPM REAL) + NimBLE ADVERTISING
 * ============================================================
 *
 * O cinto envia um pacote BINÁRIO de tamanho fixo (24 bytes) no
 * Manufacturer Data, logo após o Company ID 0xFFFF:
 *
 *  Byte  Tam  Campo       Descrição
 *  ----  ---  ----------  ------------------------------------------
 *   0     5   magic       "OQPNB" (identificação para o filtro)
 *   5     1   versao      PROTO_VERSION (2)
 *   6     1   belt_num    Número do cinto (BELT_NUM)
 *   7     1   seq         Contador 0..255 (detecta pacotes repetidos)
 *   8     2   ax          int16, aceleração X em mili-g
 *  10     2   ay          int16, aceleração Y em mili-g
 *  12     2   az          int16, aceleração Z em mili-g
 *  14     2   gx          int16, giro X em 0.1 graus/s
 *  16     2   gy          int16, giro Y em 0.1 graus/s
 *  18     2   gz          int16, giro Z em 0.1 graus/s
 *  20     1   bpm         uint8, batimentos por minuto (0 = sem leitura)
 *  21     1   flags       bit0 = eletrodos soltos
 *                         bit1 = erro no MPU6050
 *                         bit2 = BPM válido (batimento detectado há < 3 s)
 *  22     2   ecg         uint16, última amostra filtrada do ECG (0..4095)
 *
 *  Todos os campos multibyte em little-endian.
 *
 *  v5 (detecção de queda): o MPU6050 é lido a 50 Hz em ±8 g / ±2000 °/s.
 *  A cada 0,5 s o cinto calcula 8 features da janela dos últimos 2,5 s
 *  (fall_features.h) e anuncia um pacote VERSÃO 3 durante ~400 ms:
 *
 *   0     5   magic       "OQPNB"
 *   5     1   versao      3
 *   6     1   belt_num
 *   7     1   win_seq     contador de janelas 0..255
 *   8    16   8 x int16   amax amin astd gmax gstd tilt jerk post_std
 *                         (escalas em fall_features.h / features.py)
 *
 *  Nos ~100 ms restantes volta para o pacote de telemetria (versão 2).
 *  O Random Forest roda no PC (detector_queda.py).
 *  Tamanho total do anúncio: Flags(3) + MfgData(2+2+24) = 31 bytes (máximo BLE).
 */

#include <Arduino.h>
#include <Wire.h> // Comunicação I2C direta e segura
#include <NimBLEDevice.h>
#include "fall_features.h"   // features da detecção de queda (igual ao features.py)

// ============================================================
// CONFIGURAÇÕES DO ECG
// ============================================================
#define FREQ_ECG_HZ   250                 // Taxa de amostragem do ECG
#define lop 3                             // AD8232 LO+
#define lom 2                            // AD8232 LO-
#define sinalCardio 4                     // Pino analógico do ECG
#define ledPin 10                         // LED de eletrodo solto
#define DEBUG_ECG 0                       // 1 = imprime o sinal p/ Serial Plotter

const unsigned long atraso_us = 1000000UL / FREQ_ECG_HZ;

// Parâmetros do detector de batimentos (pico R)
#define REFRATARIO_MS   250     // Ignora picos a menos de 250 ms (máx 240 BPM)
#define RR_MIN_MS       300     // 200 BPM
#define RR_MAX_MS       2000    // 30 BPM
#define TIMEOUT_BPM_MS  3000    // Sem batimento por 3 s -> BPM inválido
// Calibrado para sinal com pico positivo em ~1968 e vale em ~1962 (amplitude ~6 ADC):
// Linha de base média fica em ~1965, pico R sobe ~3 a 4 unidades acima da linha base.
#define LIMIAR_MINIMO   1.8f    // Limiar mínimo calibrado para amplitude de 5 a 7 ADC
#define N_RR            5       // Nº de intervalos RR na mediana

// Estado do filtro / detector
float linhaBase  = 0;           // Média lenta (remove o nível DC)
float sinalFilt  = 0;           // Sinal passa-faixa simples
float envelope   = 0;           // Envelope de picos (limiar adaptativo)
bool  acimaLimiar = false;
unsigned long ultimoBatimento = 0;
uint16_t rr[N_RR];
uint8_t  nRR = 0, idxRR = 0;
bool  filtroIniciado = false;

int      ecgAmostra = 0;        // Última amostra (ADC) suavizada
uint8_t  bpm = 0;               // Batimentos por minuto (REAL)
bool     bpmValido = false;
bool     eletrodosSoltos = false;

// ============================================================
// CONFIGURAÇÕES DO MPU6050
// ============================================================
#define MPU_ADDRESS 0x68
float dpsGX, dpsGY, dpsGZ;
float gForceAX, gForceAY, gForceAZ;
bool  mpuOk = false;

// ============================================================
// CONFIGURAÇÕES DO BLE
// ============================================================
#define DEVICE_NAME "CINTO_OQPNB01"
#define BELT_ID "OQPNB01"
#define BELT_NUM 1
#define PROTO_VERSION 2
#define PROTO_FEAT    3
#define ADVERTISING_INTERVAL 80  // 50ms (unidade de 0,625 ms): mais cópias de cada janela

// Pacote binário (ver tabela no topo do arquivo)
struct __attribute__((packed)) PacoteCinto {
  char     magic[5];
  uint8_t  versao;
  uint8_t  beltNum;
  uint8_t  seq;
  int16_t  ax, ay, az;   // mili-g
  int16_t  gx, gy, gz;   // 0.1 dps
  uint8_t  bpm;
  uint8_t  flags;
  uint16_t ecg;
};
static_assert(sizeof(PacoteCinto) == 24, "PacoteCinto precisa ter 24 bytes");

#define FLAG_ELETRODO_SOLTO 0x01
#define FLAG_ERRO_MPU       0x02
#define FLAG_BPM_VALIDO     0x04

uint8_t seqPacote = 0;
uint8_t seqJanela = 0;

// Detecção de queda: MPU a 50 Hz e pacote de janela por FEAT_HOLD_MS
#define MPU_PERIODO_US 20000UL   // 50 Hz
#define FEAT_HOLD_MS   400       // tempo anunciando o pacote de janela (v3)
unsigned long tempo_anterior_mpu = 0;
unsigned long tempo_inicio_feat = 0;
bool anunciandoFeat = false;

// ============================================================
// CONTROLE DE TEMPO (NÃO BLOQUEANTE)
// ============================================================
unsigned long tempo_anterior_ecg = 0;
unsigned long tempo_anterior_ble = 0;
unsigned long intervalo_ble_ms = 250; // Atualiza a cada 250ms

// ============================================================
// FUNÇÕES SEGURAS DO MPU6050 (Sem travar o ESP32)
// ============================================================
static void escreverRegMPU(uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(reg);
  Wire.write(valor);
  Wire.endTransmission();
}

void iniciarMPU_Seguro() {
  escreverRegMPU(0x6B, 0x01); // acorda, clock pelo PLL do giro X
  escreverRegMPU(0x1A, 0x04); // filtro passa-baixa ~20 Hz (anti-aliasing p/ 50 Hz)
  escreverRegMPU(0x19, 19);   // 1 kHz / (1+19) = 50 Hz
  escreverRegMPU(0x1B, 0x18); // giro ±2000 °/s  -> 16,4 LSB/(°/s)
  escreverRegMPU(0x1C, 0x10); // acel ±8 g       -> 4096 LSB/g
}

void lerMPU_Seguro() {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x3B); // Endereço inicial dos dados do acelerômetro
  if (Wire.endTransmission(false) != 0) {
    // Se a comunicação falhar, não congela! Apenas avisa e sai.
    Serial.println("Erro: MPU6050 desconectado ou falha no I2C!");
    mpuOk = false;
    iniciarMPU_Seguro(); // Tenta acordar de novo (caso tenha sido religado)
    return;
  }

  // Pede 14 bytes (6 Acel + 2 Temp + 6 Giro)
  Wire.requestFrom(MPU_ADDRESS, 14, true);

  // SE o sensor responder com os 14 bytes, fazemos a leitura
  if (Wire.available() == 14) {
    int16_t rawAX = Wire.read() << 8 | Wire.read();
    int16_t rawAY = Wire.read() << 8 | Wire.read();
    int16_t rawAZ = Wire.read() << 8 | Wire.read();
    
    // Ignora temperatura (2 bytes)
    Wire.read(); Wire.read();
    
    int16_t rawGX = Wire.read() << 8 | Wire.read();
    int16_t rawGY = Wire.read() << 8 | Wire.read();
    int16_t rawGZ = Wire.read() << 8 | Wire.read();

    // Converte para ±8 g (4096 LSB/g) e ±2000 °/s (16,4 LSB/(°/s))
    gForceAX = rawAX / 4096.0f;
    gForceAY = rawAY / 4096.0f;
    gForceAZ = rawAZ / 4096.0f;
    
    dpsGX = rawGX / 16.4f;
    dpsGY = rawGY / 16.4f;
    dpsGZ = rawGZ / 16.4f;
    mpuOk = true;
  } else {
    mpuOk = false;
    while (Wire.available()) Wire.read(); // descarta lixo
  }
}

// ============================================================
// ECG: DETECÇÃO DE BATIMENTOS (PICO R) E CÁLCULO DO BPM
// ============================================================
void resetarDetector() {
  filtroIniciado = false;
  envelope = 0;
  acimaLimiar = false;
  nRR = 0;
  idxRR = 0;
  bpm = 0;
  bpmValido = false;
}

uint16_t medianaRR() {
  uint16_t tmp[N_RR];
  for (uint8_t i = 0; i < nRR; i++) tmp[i] = rr[i];
  // Ordenação simples (no máximo 5 elementos)
  for (uint8_t i = 1; i < nRR; i++) {
    uint16_t v = tmp[i];
    int8_t j = i - 1;
    while (j >= 0 && tmp[j] > v) { tmp[j + 1] = tmp[j]; j--; }
    tmp[j + 1] = v;
  }
  return tmp[nRR / 2];
}

void processarAmostraECG(int x, unsigned long agora_ms) {
  if (!filtroIniciado) {
    linhaBase = x;
    sinalFilt = 0;
    filtroIniciado = true;
  }

  // 1) Passa-alta: remove o nível DC / respiração (média lenta, ~0.6 Hz)
  linhaBase += 0.015f * (x - linhaBase);
  float hp = x - linhaBase;

  // 2) Passa-baixa leve: suaviza ruídos de alta frequência
  sinalFilt += 0.45f * (hp - sinalFilt);
  ecgAmostra = constrain((int)(linhaBase + sinalFilt), 0, 4095);

  // 3) Envelope de picos dinâmico
  // Com pico em ~1968 e linha base em ~1965, sinalFilt atinge ~3.0 a 4.0 no pico R.
  envelope *= 0.990f; // decaimento adequado
  if (sinalFilt > envelope) envelope = sinalFilt;

  // Limiar: 60% do envelope atual, com piso de 1.8f e teto adaptativo
  float limiar = max(0.6f * envelope, LIMIAR_MINIMO);

#if DEBUG_ECG
  Serial.print("ecg_raw:"); Serial.print(x);
  Serial.print(",sinal:"); Serial.print(sinalFilt);
  Serial.print(",limiar:"); Serial.println(limiar);
#endif

  // 4) Detecção: borda de subida acima do limiar + período refratário
  if (!acimaLimiar && sinalFilt > limiar) {
    acimaLimiar = true;
    unsigned long intervalo = agora_ms - ultimoBatimento;

    if (intervalo >= REFRATARIO_MS) {
      if (ultimoBatimento != 0 && intervalo >= RR_MIN_MS && intervalo <= RR_MAX_MS) {
        rr[idxRR] = (uint16_t)intervalo;
        idxRR = (idxRR + 1) % N_RR;
        if (nRR < N_RR) nRR++;

        if (nRR >= 2) {
          uint16_t m = medianaRR();
          bpm = (uint8_t)constrain((60000UL + m / 2) / m, 0, 255);
          bpmValido = true;
        }
      }
      ultimoBatimento = agora_ms;
    }
  } else if (acimaLimiar && sinalFilt < 0.35f * limiar) {
    acimaLimiar = false; // histerese com retorno abaixo de 35% do limiar
  }

  // 5) Sem batimentos há muito tempo -> BPM inválido
  if (bpmValido && agora_ms - ultimoBatimento > TIMEOUT_BPM_MS) {
    bpmValido = false;
    bpm = 0;
    nRR = 0;
  }
}

// ============================================================
// FUNÇÃO: MONTAR PACOTES (Advertising + Scan Response)
// ============================================================
// O pacote de advertising tem no máximo 31 bytes:
//   Flags (3) + Manufacturer Data (2 hdr + 2 Company ID + 24 dados) = 31
// O NOME (que também contém o código "OQPNB") vai no SCAN RESPONSE,
// que é outro pacote de 31 bytes enviado quando o anchor faz scan ativo.
void aplicarPacotes(const uint8_t *payload, size_t len) {
  NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();

  // --- Pacote principal: flags + dados dos sensores ---
  NimBLEAdvertisementData advertisementData;
  advertisementData.setFlags(0x06);

  // INJEÇÃO DO COMPANY ID (OBRIGATÓRIO) - 0xFFFF (Teste/Desenvolvimento)
  std::string mfgData = "";
  mfgData += (char)0xFF; // Company ID - Byte 1
  mfgData += (char)0xFF; // Company ID - Byte 2
  mfgData.append((const char *)payload, len); // binário (pode conter 0x00)
  advertisementData.setManufacturerData(mfgData);

  // --- Scan Response: nome completo (contém "OQPNB") ---
  NimBLEAdvertisementData scanResponseData;
  scanResponseData.setName(DEVICE_NAME);

  advertising->setAdvertisementData(advertisementData);
  advertising->setScanResponseData(scanResponseData);
  advertising->enableScanResponse(true);
}

PacoteCinto montarPacote() {
  PacoteCinto p;
  memcpy(p.magic, "OQPNB", 5);
  p.versao  = PROTO_VERSION;
  p.beltNum = BELT_NUM;
  p.seq     = seqPacote++;
  p.ax = (int16_t)constrain(lroundf(gForceAX * 1000.0f), -32768, 32767);
  p.ay = (int16_t)constrain(lroundf(gForceAY * 1000.0f), -32768, 32767);
  p.az = (int16_t)constrain(lroundf(gForceAZ * 1000.0f), -32768, 32767);
  p.gx = (int16_t)constrain(lroundf(dpsGX * 10.0f), -32768, 32767);
  p.gy = (int16_t)constrain(lroundf(dpsGY * 10.0f), -32768, 32767);
  p.gz = (int16_t)constrain(lroundf(dpsGZ * 10.0f), -32768, 32767);
  p.bpm   = bpmValido ? bpm : 0;
  p.flags = (eletrodosSoltos ? FLAG_ELETRODO_SOLTO : 0) |
            (!mpuOk          ? FLAG_ERRO_MPU       : 0) |
            (bpmValido       ? FLAG_BPM_VALIDO     : 0);
  p.ecg   = (uint16_t)ecgAmostra;
  return p;
}

// ============================================================
// FUNÇÃO: CONFIGURAR ADVERTISING INICIAL
// ============================================================
void setupAdvertising() {
  NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();
  advertising->stop();

  PacoteCinto p = montarPacote();
  aplicarPacotes((const uint8_t *)&p, sizeof(p));

  advertising->setMinInterval(ADVERTISING_INTERVAL);
  advertising->setMaxInterval(ADVERTISING_INTERVAL);
  advertising->start();

  Serial.println("\nBLE ADVERTISING INICIADO (NimBLE)");
}


// ============================================================
// FUNÇÃO: ATUALIZAR ADVERTISING (Formatação Correta NimBLE)
// ============================================================
void atualizarAdvertising() {
  NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();

  PacoteCinto p = montarPacote();

  // 1. Pára o rádio para preparar os novos dados
  advertising->stop();

  // 2. Monta advertising (dados) + scan response (nome)
  aplicarPacotes((const uint8_t *)&p, sizeof(p));

  // 3. Reinicia a transmissão
  advertising->start();

#if !DEBUG_ECG
  Serial.printf("BLE TX #%u: A=(%.2f, %.2f, %.2f)g G=(%.1f, %.1f, %.1f)dps "
                "BPM=%u%s ECG=%u%s%s\n",
                p.seq, p.ax / 1000.0, p.ay / 1000.0, p.az / 1000.0,
                p.gx / 10.0, p.gy / 10.0, p.gz / 10.0,
                p.bpm, bpmValido ? "" : "(--)", p.ecg,
                eletrodosSoltos ? " [ELETRODOS SOLTOS]" : "",
                mpuOk ? "" : " [ERRO MPU]");
#endif
}

// ============================================================
// DETECÇÃO DE QUEDA: ANUNCIAR PACOTE DE JANELA (v3)
// ============================================================
void anunciarJanela() {
  int16_t f[FF_NFEAT];
  ff_compute(f);
  uint8_t pkt[24];
  ff_build_packet(pkt, BELT_NUM, seqJanela++, f);

  NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();
  advertising->stop();
  aplicarPacotes(pkt, sizeof(pkt));
  advertising->start();

#if !DEBUG_ECG
  Serial.printf("JANELA #%u: amax=%.2fg amin=%.2fg gmax=%.0fdps tilt=%.0f\n",
                (uint8_t)(seqJanela - 1), f[0] / 1000.0, f[1] / 1000.0, f[3] / 5.0, f[5] / 100.0);
#endif
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n=================================");
  Serial.println("INICIALIZANDO CINTO");
  Serial.println("=================================");

  // Inicializa I2C com timeout (evita congelamento em nível de hardware)
  Wire.begin();
  Wire.setTimeOut(100); 

  iniciarMPU_Seguro();

  pinMode(lop, INPUT);
  pinMode(lom, INPUT);
  pinMode(ledPin, OUTPUT);
  analogReadResolution(12);

  resetarDetector();

  Serial.println("Inicializando BLE (NimBLE)...");
  NimBLEDevice::init(DEVICE_NAME);

  setupAdvertising();

  Serial.println("Cinto inicializado.\n");
}

// ============================================================
// LOOP
// ============================================================
void loop() {
  unsigned long tempo_atual_micros = micros();
  unsigned long tempo_atual_millis = millis();

  // ==========================================================
  // TAREFA 1: LER O ECG a 250Hz E DETECTAR BATIMENTOS
  // ==========================================================
  if (tempo_atual_micros - tempo_anterior_ecg >= atraso_us) {
    tempo_anterior_ecg += atraso_us;
    // Se atrasou muito (ex.: BLE ocupado), ressincroniza sem "rajada"
    if (tempo_atual_micros - tempo_anterior_ecg > 10 * atraso_us) {
      tempo_anterior_ecg = tempo_atual_micros;
    }

    if (digitalRead(lop) == HIGH || digitalRead(lom) == HIGH) {
      digitalWrite(ledPin, HIGH);
      if (!eletrodosSoltos) resetarDetector();
      eletrodosSoltos = true;
    } else {
      digitalWrite(ledPin, LOW);
      eletrodosSoltos = false;
      processarAmostraECG(analogRead(sinalCardio), tempo_atual_millis);
    }
  }

  // ==========================================================
  // TAREFA 2: LER O MPU A 50 Hz E ALIMENTAR A JANELA DE QUEDA
  // ==========================================================
  if (tempo_atual_micros - tempo_anterior_mpu >= MPU_PERIODO_US) {
    tempo_anterior_mpu += MPU_PERIODO_US;
    if (tempo_atual_micros - tempo_anterior_mpu > 5 * MPU_PERIODO_US) {
      tempo_anterior_mpu = tempo_atual_micros; // atrasou demais: ressincroniza
    }
    lerMPU_Seguro();
    if (mpuOk) {
      ff_push(gForceAX, gForceAY, gForceAZ, dpsGX, dpsGY, dpsGZ);
    }
    if (ff_ready()) {                 // a cada 25 amostras (0,5 s)
      anunciarJanela();
      anunciandoFeat = true;
      tempo_inicio_feat = tempo_atual_millis;
    }
  }

  // ==========================================================
  // TAREFA 3: TELEMETRIA (v2) NOS INTERVALOS ENTRE JANELAS
  // ==========================================================
  if (anunciandoFeat) {
    if (tempo_atual_millis - tempo_inicio_feat >= FEAT_HOLD_MS) {
      anunciandoFeat = false;
      tempo_anterior_ble = tempo_atual_millis;
      atualizarAdvertising();         // volta para o pacote de telemetria
    }
  } else if (tempo_atual_millis - tempo_anterior_ble >= intervalo_ble_ms) {
    tempo_anterior_ble = tempo_atual_millis;
    atualizarAdvertising();
  }
}