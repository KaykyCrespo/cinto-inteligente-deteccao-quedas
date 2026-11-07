"""
Features de janela usadas no treino (scripts/treino_sisfall.py) e na detecção em tempo real
(detector_queda.py). Este arquivo é a referência única: treino e operação usam a mesma função.

Entrada de uma janela: 2,5 s de amostras, com
  acc em g  (ax, ay, az)  e  giro em °/s (gx, gy, gz).

A taxa (fs) é um parâmetro; o MVP usa 100 Hz (dados crus via GATT, features calculadas no PC).
"""
import numpy as np

FS = 100                # Hz (taxa do cinto_mvp_v1)
WIN_S = 2.5             # duração da janela [s]
STEP_S = 0.5            # passo entre janelas [s]
SEG_S = 0.5             # trecho inicial/final usado em tilt e post_std [s]
WIN = int(WIN_S * FS)   # 250 amostras a 100 Hz
STEP = int(STEP_S * FS)
SEG = int(SEG_S * FS)


def tamanhos(fs):
    """(win, step, seg) em amostras para a taxa fs."""
    return int(round(WIN_S * fs)), int(round(STEP_S * fs)), int(round(SEG_S * fs))
ACC_RANGE_G = 8.0       # MPU6050 configurado em ±8 g
GYRO_RANGE_DPS = 2000.0 # MPU6050 configurado em ±2000 °/s

FEATURES = [
    "amax",      # máx |a|            [g]
    "amin",      # mín |a| (queda livre) [g]
    "astd",      # desvio de |a|       [g]
    "gmax",      # máx |w|            [°/s]
    "gstd",      # desvio de |w|       [°/s]
    "tilt",      # ângulo entre a gravidade do início e do fim [graus]
    "jerk",      # máx variação de |a| por segundo [g/s]
    "post_std",  # desvio de |a| no último 0,5 s (pessoa parada após impacto) [g]
]
NAMES = list(FEATURES)


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


def sliding_windows(acc, gyr, fs=FS):
    """Gera (inicio, features) para todas as janelas de um registro."""
    win, step, _ = tamanhos(fs)
    for s in range(0, len(acc) - win + 1, step):
        yield s, window_features(acc[s:s + win], gyr[s:s + win], fs)
