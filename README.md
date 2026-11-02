# Detecção de queda: SisFall + Random Forest (RF rodando no PC)

## TCC MVP (dados crus via GATT a 100 Hz, MPU em ±8 g / ±2000 °/s)
O cinto manda as leituras cruas do MPU6050 a 100 Hz, a antena repassa por MQTT e o PC
monta janelas de 2,5 s, calcula 8 features e roda o Random Forest treinado no SisFall.

| Arquivo | O que é |
|---|---|
| `Arduino/cinto_mvp_v1/` | cinto: MPU em ±8 g / ±2000 °/s, filtro interno 44 Hz, 100 Hz, contador `seq` no pacote. |
| `Arduino/anchor_mvp_v1/` | antena: repassa o pacote do cinto sem alterar. |
| `app.py` | painel Streamlit: cintos, gráficos, alarme de queda, gravação e download de CSV. |
| `interface_mvp_2.py` | a mesma coisa no terminal. |
| `modelo_mvp_8g.joblib` | Random Forest treinado no SisFall a 100 Hz, ±8 g / ±2000 °/s. |
| `treino_sisfall.py` | refaz o treino (os padrões já são 100 Hz, ±8 g, ±2000 °/s). |
| `reproduzir_csv.py` | roda o detector em cima de um CSV gravado (teste sem hardware). |
| `detector_queda.py`, `features.py` | usados pelos scripts acima; deixe na mesma pasta. |

As faixas do `iniciarMPU()` no cinto **precisam** ser as mesmas do modelo. Se mudar alguma, treine de novo
com `--faixa-acc` e `--faixa-giro`.

```
pip install numpy scipy scikit-learn==1.9.1 joblib paho-mqtt streamlit pandas

# refazer o treino (uns 6 minutos)
python treino_sisfall.py --sisfall C:\caminho\SisFall_dataset

# painel
python -m streamlit run app.py

# ou terminal
python interface_mvp_2.py --modelo modelo_mvp_8g.joblib --quiet --csv leituras.csv --csv-janelas janelas.csv

# testar um CSV gravado
python reproduzir_csv.py gravacoes\amostras_AAAAMMDD_HHMMSS.csv --modelo modelo_mvp_8g.joblib
```

### CSV no Streamlit
- Na barra lateral, **Anotação** marca o que está acontecendo (ex.: "queda frente 1"). Ela vai em cada linha gravada.
- **Gravar amostras** salva `gravacoes/amostras_<data>.csv` e `gravacoes/janelas_<data>.csv` enquanto estiver ligado.
- No fim da página, **Baixar CSV**: janelas analisadas, quedas detectadas e as amostras da última gravação.

Resultado no SisFall (validação por voluntário, limiar 0,5): 98,8% das quedas detectadas,
95,3% de especificidade. Detalhes em `resultado_treino_mvp_8g.txt`.

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
