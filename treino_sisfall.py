"""
Treina o Random Forest de detecção de queda com o SisFall.

Uso:
    python treino_sisfall.py --sisfall CAMINHO/SisFall_dataset --saida modelo_queda.joblib

Estrutura esperada do SisFall (como vem no zip oficial):
    SisFall_dataset/SA01/D01_SA01_R01.txt, F05_SA01_R03.txt, ...
Cada linha: 9 valores separados por vírgula terminando em ';'
    ADXL345 (ax,ay,az) | ITG3200 (gx,gy,gz) | MMA8451Q (ax,ay,az), a 200 Hz.

Passos:
 1. converte bruto -> g e °/s  (fórmula do readme do SisFall)
 2. reamostra 200 Hz -> 50 Hz e satura em ±8 g / ±2000 °/s (igual ao MPU6050 do cinto)
 3. quedas (F**): janelas com o pico de impacto entre 0,5 s e 2,0 s da janela
    atividades (D**): todas as janelas deslizantes com passo de 0,5 s
 4. validação cruzada separando por voluntário (GroupKFold)
 5. treina o modelo final com tudo e salva
"""
import argparse, re, sys
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupKFold
import joblib

from features import (FS, WIN, STEP, ACC_RANGE_G, GYRO_RANGE_DPS, NAMES,
                      window_features, quantize, sliding_windows)

ACC_K = (2 * 16) / 2 ** 13       # ADXL345: ±16 g, 13 bits
GYR_K = (2 * 2000) / 2 ** 16     # ITG3200: ±2000 °/s, 16 bits
NUM = re.compile(r"-?\d+")


def load_trial(path):
    rows = []
    for line in Path(path).read_text(errors="ignore").splitlines():
        v = NUM.findall(line)
        if len(v) >= 6:
            rows.append(v[:6])
    raw = np.array(rows, dtype=np.float64)
    acc = raw[:, 0:3] * ACC_K
    gyr = raw[:, 3:6] * GYR_K
    # 200 -> 50 Hz com filtro anti-aliasing
    acc = resample_poly(acc, 1, 4, axis=0)
    gyr = resample_poly(gyr, 1, 4, axis=0)
    acc = np.clip(acc, -ACC_RANGE_G, ACC_RANGE_G)
    gyr = np.clip(gyr, -GYRO_RANGE_DPS, GYRO_RANGE_DPS)
    return acc.astype(np.float32), gyr.astype(np.float32)


def fall_windows(acc, gyr, offsets=range(25, 101, 5)):
    am = np.linalg.norm(acc, axis=1)
    p = int(am.argmax())
    for off in offsets:
        s = p - off
        if 0 <= s and s + WIN <= len(acc):
            yield window_features(acc[s:s + WIN], gyr[s:s + WIN])


def build_dataset(root):
    X, y, grp, trial_id, train_mask = [], [], [], [], []
    trials = []  # (trial_idx, subject, is_fall, activity, runtime windows)
    files = sorted(Path(root).glob("S*/[DF][0-9][0-9]_*.txt"))
    if not files:
        sys.exit(f"Nenhum arquivo do SisFall encontrado em {root}")
    for t, f in enumerate(files):
        act, subj = f.stem.split("_")[:2]
        is_fall = act.startswith("F")
        acc, gyr = load_trial(f)
        if len(acc) < WIN:
            continue
        # janelas como o cinto vai mandar (passo 0,5 s) -> usadas na avaliação por evento
        rt = np.array([quantize(v) for _, v in sliding_windows(acc, gyr)])
        trials.append((t, subj, is_fall, act, rt))
        feats = list(fall_windows(acc, gyr)) if is_fall else list(rt)
        for v in feats:
            X.append(quantize(v)); y.append(int(is_fall)); grp.append(subj); trial_id.append(t)
        if t % 200 == 0:
            print(f"  {t}/{len(files)} arquivos...", flush=True)
    return np.array(X), np.array(y), np.array(grp), np.array(trial_id), trials


def make_model():
    return RandomForestClassifier(n_estimators=200, min_samples_leaf=2,
                                  class_weight="balanced_subsample",
                                  n_jobs=-1, random_state=42)


def trial_max_probs(model, trials, subjects):
    """Maior probabilidade de queda em cada ensaio dos voluntários de teste."""
    return [(act, is_fall, float(model.predict_proba(rt)[:, 1].max()))
            for _, subj, is_fall, act, rt in trials if subj in subjects]


def resumo(res, thr):
    tp = sum(f and p >= thr for _, f, p in res); fn = sum(f and p < thr for _, f, p in res)
    fp = sum((not f) and p >= thr for _, f, p in res); tn = sum((not f) and p < thr for _, f, p in res)
    return tp, fn, fp, tn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sisfall", required=True)
    ap.add_argument("--saida", default="modelo_queda.joblib")
    ap.add_argument("--limiar", type=float, default=0.5)
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()

    print("Lendo SisFall...")
    X, y, grp, _, trials = build_dataset(a.sisfall)
    print(f"Janelas: {len(y)}  (quedas {y.sum()}, atividades {len(y) - y.sum()})  "
          f"voluntários: {len(set(grp))}")

    print(f"\nValidação cruzada por voluntário ({a.folds} folds), limiar {a.limiar}:")
    todos = []
    for k, (tr, te) in enumerate(GroupKFold(a.folds).split(X, y, grp)):
        m = make_model().fit(X[tr], y[tr])
        res = trial_max_probs(m, trials, set(grp[te]))
        todos += res
        tp, fn, fp, tn = resumo(res, a.limiar)
        print(f"  fold {k + 1}: sensibilidade {tp / max(tp + fn, 1):.3f}  "
              f"especificidade {tn / max(tn + fp, 1):.3f}")
    TP, FN, FP, TN = resumo(todos, a.limiar)
    sens = TP / max(TP + FN, 1); spec = TN / max(TN + FP, 1)
    print(f"\nPor ensaio (queda detectada em algum momento do registro):")
    print(f"  Sensibilidade {sens:.3f}  ({TP}/{TP + FN} quedas detectadas)")
    print(f"  Especificidade {spec:.3f}  ({FP} alarmes falsos em {TN + FP} atividades)")

    print("\nEfeito do limiar (escolha conforme o custo de um alarme falso x uma queda perdida):")
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        tp, fn, fp, tn = resumo(todos, thr)
        print(f"  limiar {thr:.1f}: sensibilidade {tp / max(tp + fn, 1):.3f}  "
              f"especificidade {tn / max(tn + fp, 1):.3f}")

    print(f"\nPor atividade (limiar {a.limiar}):")
    for act in sorted({r[0] for r in todos}):
        rs = [r for r in todos if r[0] == act]
        n_hit = sum(p >= a.limiar for _, _, p in rs)
        tipo = "detectadas" if act.startswith("F") else "alarmes falsos"
        print(f"  {act}: {n_hit}/{len(rs)} {tipo}")

    model = make_model().fit(X, y)
    imp = sorted(zip(model.feature_importances_, NAMES), reverse=True)
    print("\nImportância das features:", ", ".join(f"{n}={v:.2f}" for v, n in imp))
    joblib.dump({"model": model, "features": NAMES, "fs": FS, "win": WIN,
                 "step": STEP, "limiar": a.limiar,
                 "cv": {"sensibilidade": sens, "especificidade": spec}}, a.saida)
    print(f"\nModelo salvo em {a.saida}")


if __name__ == "__main__":
    main()
