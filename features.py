"""
Features de janela usadas no treino (SisFall) e na detecção em tempo real.

IMPORTANTE: este arquivo é a referência. O firmware (Arduino/cinto_v5/fall_features.h)
implementa exatamente as mesmas contas. Se mudar algo aqui, mude lá também e
rode `python teste_paridade.py`.

Entrada de uma janela: 2,5 s de amostras, com
  acc em g  (ax, ay, az)  e  giro em °/s (gx, gy, gz).

A taxa (fs) é um parâmetro: 50 Hz no cinto_v5 (features no cinto) e
100 Hz no MVP (dados crus via GATT, features calculadas no PC).
"""
import numpy as np

FS = 50                 # Hz (padrão do cinto_v5; o MVP usa 100)
WIN_S = 2.5             # duração da janela [s]
STEP_S = 0.5            # passo entre janelas [s]
SEG_S = 0.5             # trecho inicial/final usado em tilt e post_std [s]
WIN = int(WIN_S * FS)   # 125 amostras a 50 Hz
STEP = int(STEP_S * FS)
SEG = int(SEG_S * FS)


def tamanhos(fs):
    """(win, step, seg) em amostras para a taxa fs."""
    return int(round(WIN_S * fs)), int(round(STEP_S * fs)), int(round(SEG_S * fs))
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


def window_features(acc, gyr, fs=FS):
    """acc, gyr: arrays (win, 3) em g e °/s. Retorna vetor float (8,)."""
    seg = tamanhos(fs)[2]
    acc = np.asarray(acc, dtype=np.float32)
    gyr = np.asarray(gyr, dtype=np.float32)
    am = np.sqrt((acc * acc).sum(1))
    gm = np.sqrt((gyr * gyr).sum(1))
    u = acc[:seg].mean(0)
    v = acc[-seg:].mean(0)
    c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9))
    tilt = np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))
    jerk = np.abs(np.diff(am)).max() * fs
    return np.array([am.max(), am.min(), am.std(), gm.max(), gm.std(),
                     tilt, jerk, am[-seg:].std()], dtype=np.float64)


def quantize(f):
    """Simula o envio pelo BLE: arredonda para int16 com a escala e volta."""
    q = np.clip(np.round(np.asarray(f) * SCALES), -32768, 32767)
    return q / SCALES


def from_int16(values):
    """Converte os 8 int16 recebidos no pacote para as unidades da feature."""
    return np.asarray(values, dtype=np.float64) / SCALES


def sliding_windows(acc, gyr, fs=FS):
    """Gera (inicio, features) para todas as janelas de um registro."""
    win, step, _ = tamanhos(fs)
    for s in range(0, len(acc) - win + 1, step):
        yield s, window_features(acc[s:s + win], gyr[s:s + win], fs)
