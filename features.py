"""
Features de janela usadas no treino (SisFall) e na detecção em tempo real.

IMPORTANTE: este arquivo é a referência. O firmware (Arduino/cinto_v5/fall_features.h)
implementa exatamente as mesmas contas. Se mudar algo aqui, mude lá também e
rode `python teste_paridade.py`.

Entrada de uma janela: N = 125 amostras a 50 Hz (2,5 s), com
  acc em g  (ax, ay, az)  e  giro em °/s (gx, gy, gz).
"""
import numpy as np

FS = 50                 # Hz (taxa do MPU6050 no cinto)
WIN = 125               # amostras por janela (2,5 s)
STEP = 25               # passo entre janelas (0,5 s)
SEG = 25                # trecho inicial/final usado em tilt e post_std (0,5 s)
ACC_RANGE_G = 8.0       # MPU6050 configurado em ±8 g
GYRO_RANGE_DPS = 2000.0 # MPU6050 configurado em ±2000 °/s

# nome da feature -> escala usada para mandar como int16 no pacote BLE
FEATURES = [
    ("amax",     1000.0),  # máx |a|            [g]
    ("amin",     1000.0),  # mín |a| (queda livre) [g]
    ("astd",     1000.0),  # desvio de |a|       [g]
    ("gmax",        5.0),  # máx |w|            [°/s]
    ("gstd",        5.0),  # desvio de |w|       [°/s]
    ("tilt",      100.0),  # ângulo entre a gravidade do início e do fim [graus]
    ("jerk",       10.0),  # máx variação de |a| por segundo [g/s]
    ("post_std", 1000.0),  # desvio de |a| no último 0,5 s (pessoa parada após impacto) [g]
]
NAMES = [n for n, _ in FEATURES]
SCALES = np.array([s for _, s in FEATURES])


def window_features(acc, gyr):
    """acc, gyr: arrays (WIN, 3) em g e °/s. Retorna vetor float (8,)."""
    acc = np.asarray(acc, dtype=np.float32)
    gyr = np.asarray(gyr, dtype=np.float32)
    am = np.sqrt((acc * acc).sum(1))
    gm = np.sqrt((gyr * gyr).sum(1))
    u = acc[:SEG].mean(0)
    v = acc[-SEG:].mean(0)
    c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9))
    tilt = np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))
    jerk = np.abs(np.diff(am)).max() * FS
    return np.array([am.max(), am.min(), am.std(), gm.max(), gm.std(),
                     tilt, jerk, am[-SEG:].std()], dtype=np.float64)


def quantize(f):
    """Simula o envio pelo BLE: arredonda para int16 com a escala e volta."""
    q = np.clip(np.round(np.asarray(f) * SCALES), -32768, 32767)
    return q / SCALES


def from_int16(values):
    """Converte os 8 int16 recebidos no pacote para as unidades da feature."""
    return np.asarray(values, dtype=np.float64) / SCALES


def sliding_windows(acc, gyr, step=STEP):
    """Gera (inicio, features) para todas as janelas de um registro."""
    for s in range(0, len(acc) - WIN + 1, step):
        yield s, window_features(acc[s:s + WIN], gyr[s:s + WIN])
