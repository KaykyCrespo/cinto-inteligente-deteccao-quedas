"""
Confere se o firmware (Arduino/cinto_v5/fall_features.h) calcula as mesmas features
que features.py. Precisa de gcc. Uso: python teste_paridade.py
"""
import subprocess, tempfile, os, sys
import numpy as np
from features import WIN, STEP, SCALES, sliding_windows

C_MAIN = r'''
#include <stdio.h>
#include "fall_features.h"
int main(void){ float a[6]; int16_t f[FF_NFEAT];
  while (scanf("%f %f %f %f %f %f", a,a+1,a+2,a+3,a+4,a+5) == 6) {
    ff_push(a[0],a[1],a[2],a[3],a[4],a[5]);
    if (ff_ready()) { ff_compute(f);
      for (int i=0;i<FF_NFEAT;i++) printf("%d%c", f[i], i==FF_NFEAT-1?'\n':' '); } }
  return 0; }
'''

def sinal_teste(n=3000, seed=0):
    r = np.random.default_rng(seed)
    t = np.arange(n) / 50
    acc = np.stack([0.1 * np.sin(2 * np.pi * 1.8 * t), 0.05 * r.standard_normal(n),
                    1 + 0.2 * np.sin(2 * np.pi * 1.8 * t)], 1)
    gyr = 30 * r.standard_normal((n, 3))
    for p in (700, 1700, 2600):           # três "quedas": queda livre, impacto, deitado
        acc[p - 15:p] *= 0.3
        acc[p:p + 5] = [6.5, -3.0, 4.0]
        acc[p + 5:] = [1, 0, 0] if p == 700 else acc[p + 5:]
        gyr[p - 20:p + 5] = 900 * r.standard_normal((25, 3))
    return np.clip(acc, -8, 8).astype(np.float32), np.clip(gyr, -2000, 2000).astype(np.float32)

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    acc, gyr = sinal_teste()
    with tempfile.TemporaryDirectory() as d:
        src, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
        open(src, "w").write(C_MAIN)
        subprocess.run(["gcc", "-O2", "-I", os.path.join(here, "Arduino", "cinto_v5"), src, "-o", exe, "-lm"], check=True)
        inp = "\n".join(" ".join(f"{x:.6f}" for x in row) for row in np.hstack([acc, gyr]))
        # arredonda a entrada do Python igual ao texto que o C leu
        acc, gyr = np.round(acc, 6), np.round(gyr, 6)
        out = subprocess.run([exe], input=inp, capture_output=True, text=True, check=True).stdout
    c = np.array([list(map(int, l.split())) for l in out.strip().splitlines()])
    py = np.array([np.clip(np.round(v * SCALES), -32768, 32767) for _, v in sliding_windows(acc, gyr)])
    # o C só emite a primeira janela quando o buffer enche (amostra 125) e depois a cada 25
    py = py[:len(c)]
    diff = np.abs(c - py).max(0)
    print("janelas comparadas:", len(c))
    print("maior diferença por feature (em unidades int16):", diff.astype(int).tolist())
    ok = (diff <= 1).all()
    print("OK: firmware e Python batem" if ok else "ERRO: firmware e Python diferem")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
