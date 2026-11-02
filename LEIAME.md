# Detecção de queda: SisFall + Random Forest (RF rodando no PC)

## Caminho atual: MVP (dados crus via GATT a 100 Hz)
O cinto manda as leituras cruas do MPU6050 a 100 Hz, a antena repassa por MQTT e o PC
monta as janelas de 2,5 s, calcula as features e roda o Random Forest.

| Arquivo | O que é |
|---|---|
| `interface_mvp_2.py` | a interface_mvp_1 + detecção de queda (`--modelo`, `--limiar`, `--csv-janelas`, `--quiet`). Aceita pacotes com ou sem `seq`. |
| `modelo_mvp_2g.joblib` | modelo para o MPU na faixa padrão (±2 g / ±250 °/s), ou seja, o **cinto_mvp_v1 como está**. |
| `modelo_mvp_8g.joblib` | modelo para o MPU em ±8 g / ±2000 °/s (**cinto_mvp_v2**). |
| `Arduino/cinto_mvp_v2/` | opcional: cinto_mvp_v1 + faixa ±8 g / ±2000 °/s + contador `seq`. A antena anchor_mvp_v1 não muda. |
| `reproduzir_csv.py` | roda o detector em cima de um CSV gravado com `--csv` (teste sem hardware). |
| `detector_queda.py`, `features.py` | usados pelos scripts acima; deixe na mesma pasta. |
| `treino_sisfall.py` | treina de novo (`--fs 100 --faixa-acc 2 --faixa-giro 250`, por exemplo). |

O modelo **tem que** ser o da mesma faixa configurada no MPU, senão a conversão de cru para g fica errada.

```
pip install numpy scipy scikit-learn==1.9.1 joblib paho-mqtt
python interface_mvp_2.py --modelo modelo_mvp_2g.joblib --quiet --csv leituras.csv --csv-janelas janelas.csv
python reproduzir_csv.py leituras.csv --modelo modelo_mvp_2g.joblib
```

Resultados no SisFall (100 Hz, validação por voluntário, limiar 0,5): veja
`resultado_treino_mvp_2g.txt` e `resultado_treino_mvp_8g.txt`.

---

# Caminho anterior: cinto_v5 (features calculadas no cinto, BLE advertising)

## Arquivos
| Arquivo | O que é |
|---|---|
| `Arduino/cinto_v5/` | cinto_v4 + MPU a 50 Hz (±8 g / ±2000 °/s) + pacote de janela v3. Grave junto com `fall_features.h` (mesma pasta). |
| `Arduino/anchor_v4/` | anchor_v3 + repassa o pacote v3 no MQTT (`"type":"feat"`). Lembre de ajustar `ANCHOR_ID`, Wi-Fi e IP. |
| `interface.py` | a sua interface + `--modelo`, `--limiar` e `--csv-janelas`. |
| `detector_queda.py`, `features.py` | usados pela interface; deixe na mesma pasta. |
| `treino_sisfall.py` | treina o RF com o SisFall e gera `modelo_queda.joblib`. |
| `teste_paridade.py` | confere se o C do cinto e o Python calculam as mesmas features. |

## Rodar
```
pip install numpy scipy scikit-learn==1.9.1 joblib paho-mqtt
python treino_sisfall.py --sisfall C:\caminho\SisFall_dataset --saida modelo_queda.joblib
python interface.py --modelo modelo_queda.joblib --csv-janelas janelas.csv
```
Sem `--modelo` a interface funciona como antes.

## Fluxo
1. **Cinto (ESP32-C3):** MPU6050 em ±8 g / ±2000 °/s, lido a 50 Hz. A cada 0,5 s calcula 8 features
   da janela dos últimos 2,5 s (`Arduino/cinto_v5/fall_features.h`) e anuncia um pacote BLE versão 3
   várias vezes seguidas (o mesmo `winSeq`), para aguentar a perda de pacotes.
2. **Âncora:** repassa o pacote versão 3 por MQTT (campo `raw` em hexadecimal, ou `feat` + `win_seq`).
3. **PC:** `detector_queda.py` descarta repetidos, roda o RF e dispara o alerta com a âncora mais próxima.

## Features (mesmas no treino e no cinto)
amax, amin, astd (módulo da aceleração), gmax, gstd (módulo do giro), tilt (ângulo entre a gravidade
do início e do fim da janela), jerk (maior variação de |a| por segundo), post_std (agitação no último 0,5 s).
Todas são independentes da orientação do sensor, por isso o eixo do SisFall não precisa bater com o do cinto.

## Conferir firmware x Python
```
python teste_paridade.py      # precisa de gcc
```

## Pacote BLE versão 3 (24 bytes após o Company ID 0xFFFF)
| Offset | Tam | Campo |
|---|---|---|
| 0 | 5 | `OQPNB` |
| 5 | 1 | versão = 3 |
| 6 | 1 | beltNum |
| 7 | 1 | winSeq (0..255) |
| 8 | 16 | 8 × int16 LE: amax×1000, amin×1000, astd×1000, gmax×5, gstd×5, tilt×100, jerk×10, post_std×1000 |

## Modelo já treinado
`modelo_queda.joblib` foi treinado com o SisFall completo (38 voluntários, 4506 ensaios) com scikit-learn 1.9.1.
Use essa mesma versão do scikit-learn para carregar; com outra versão, rode o treino de novo no seu PC.
Os números da validação estão em `resultado_treino_sisfall.txt`.
