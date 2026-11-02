"""
Roda o detector de queda em cima de um CSV gravado pela interface_mvp
(--csv), como se os dados estivessem chegando ao vivo. Bom para testar
sem o hardware e para medir sensibilidade/especificidade das suas gravações.

Uso:
    python reproduzir_csv.py leituras_mvp.csv --modelo modelo_mvp_2g.joblib
    python reproduzir_csv.py leituras_mvp.csv --modelo modelo_mvp_8g.joblib --saida janelas.csv
"""
import argparse, csv
from datetime import datetime
from detector_queda import DetectorQuedaStream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--limiar", type=float, default=None)
    ap.add_argument("--saida", default=None, help="CSV com todas as janelas analisadas")
    a = ap.parse_args()

    det = DetectorQuedaStream(a.modelo, limiar=a.limiar)
    print(f"Modelo: {det.fs} Hz, ±{det.faixa_acc:g} g / ±{det.faixa_giro:g} °/s, limiar {det.limiar:.2f}")
    janelas, quedas, n = [], [], 0
    with open(a.csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            n += 1
            ts = datetime.fromisoformat(r["timestamp"])
            seq = int(r["seq"]) if r.get("seq") not in (None, "") else None
            raw = tuple(int(r[k]) for k in ("ax", "ay", "az", "gx", "gy", "gz"))
            j = det.adicionar(int(r["id_cinto"]), int(r["id_antena"]), int(r["rssi"]), raw,
                              seq=seq, agora=ts.timestamp())
            if j:
                j["timestamp"] = r["timestamp"]
                janelas.append(j)
                if j["queda"]:
                    quedas.append(j)

    print(f"{n} amostras, {len(janelas)} janelas analisadas, {len(quedas)} quedas detectadas\n")
    for j in quedas:
        f = j["features"]
        print(f"  {j['timestamp']}  prob {j['prob']:.2f}  amax {f['amax']:.2f} g  "
              f"tilt {f['tilt']:.0f}°  gmax {f['gmax']:.0f} °/s")
    if a.saida:
        cols = ["timestamp", "belt", "anchor", "prob", "queda"] + list(janelas[0]["features"]) if janelas else []
        with open(a.saida, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for j in janelas:
                w.writerow({"timestamp": j["timestamp"], "belt": j["belt"], "anchor": j["anchor"],
                            "prob": round(j["prob"], 4), "queda": j["queda"], **j["features"]})
        print(f"\nJanelas salvas em {a.saida}")


if __name__ == "__main__":
    main()
