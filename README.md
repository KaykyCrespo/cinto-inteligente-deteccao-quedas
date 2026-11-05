# OQPNB — Cinto Inteligente: detecção de queda e localização indoor (TCC MVP)

O cinto (ESP32-C3 + MPU6050 + AD8232) envia leituras cruas a 100 Hz por BLE (GATT) para uma antena,
que repassa por MQTT. As demais antenas escutam os anúncios BLE e medem RSSI. No PC, o painel Streamlit
monta janelas de 2,5 s, calcula 8 características, roda um Random Forest treinado no SisFall, estima o
quadrante do ambiente, dispara alerta no Telegram e persiste tudo em SQLite.

## Estrutura do projeto

```
TCC MVP/
├── app.py                 painel Streamlit (ponto de entrada)
├── alerta_telegram.py     envio de alertas pelo bot do Telegram
├── banco.py               persistência SQLite (sessões, amostras, janelas, quedas, status)
├── detector_queda.py      janelas + Random Forest em tempo real
├── features.py            as 8 características (referência para treino e detecção)
├── interface_mvp_2.py     parser do pacote MQTT e versão do monitor em terminal
├── localizacao.py         RSSI -> distância -> quadrante (com confiança e retenção)
├── requirements.txt
├── Arduino/               firmware do cinto (cinto_mvp_v1) e da antena (anchor_mvp_v1) + bibliotecas
├── assets/                logo
├── modelos/               modelo_mvp_8g.joblib e o relatório do treino
├── scripts/               treino_sisfall.py, reproduzir_csv.py
├── tests/                 testes automatizados (localização, controle do Telegram)
├── dados/
│   ├── oqpnb.db           banco SQLite (criado ao abrir o painel; ignorado pelo git)
│   ├── gravacoes/         CSV de amostras do botão "Gravar amostras" (ignorado pelo git)
│   ├── ensaios_rssi/      CSVs e resultados dos ensaios de calibração de RSSI
│   └── SISFALL/           dataset público usado no treino
├── docs/                  banco_de_dados.md (DER, modelo lógico/físico, dicionário), documentação e READMEs antigos
└── legado/                interface antiga, teste de paridade C/Python e README do caminho cinto_v5
```

Os módulos Python da raiz se importam entre si pelo nome; mantenha-os juntos. Scripts e testes
ajustam o `sys.path` sozinhos e podem ser executados de qualquer pasta.

## Instalação e execução

```powershell
pip install -r requirements.txt

# painel (abre http://localhost:8501)
python -m streamlit run app.py

# alerta Telegram (opcional): defina antes de abrir o painel
$env:OQPNB_TG_TOKEN="token do BotFather"; $env:OQPNB_TG_CHAT="chat_id"

# monitor em terminal
python interface_mvp_2.py --modelo modelos/modelo_mvp_8g.joblib --quiet

# reproduzir um CSV gravado sem hardware
python scripts/reproduzir_csv.py dados/gravacoes/amostras_X.csv --modelo modelos/modelo_mvp_8g.joblib

# refazer o treino (~6 min)
python scripts/treino_sisfall.py --sisfall dados/SISFALL/SisFall_dataset --saida modelos/modelo_mvp_8g.joblib

# testes
python -m unittest discover -s tests -p "teste_*.py" -v
```

Variáveis de ambiente opcionais: `OQPNB_BROKER`, `OQPNB_PORT`, `OQPNB_MODELO`, `OQPNB_DB`,
`OQPNB_LADO_M`, `OQPNB_RSSI_1M`, `OQPNB_N_PERDA`, `OQPNB_OFFSET_GATT`.

As faixas do `iniciarMPU()` no cinto (±8 g / ±2000 °/s) **precisam** ser as mesmas do modelo.
Se mudar alguma, treine de novo com `--faixa-acc` e `--faixa-giro`.

## Painel

- **Monitoramento**: cartão por cinto (status normal / possível queda com data, hora, antena, quadrante
  e contagem regressiva do aviso), broker, amostras, taxa, eletrodos, antenas online, Telegram,
  probabilidade de queda (8 últimas janelas, 0–100 %) e tabela de quedas.
- **Detalhes**: status do sistema (modelo, limiar, pacotes inválidos, amostras perdidas, janelas
  reiniciadas, quantidade de quedas), antenas (GATT/Advertising, RSSI, mais perto), tabela RSSI,
  histórico de quedas, gráficos de sinais, mapa indoor com raios de distância, ECG e exportação.
- **Barra lateral**: envio de alertas no Telegram (toggle + teste), limiar, tempo para resetar o
  aviso de queda (1–5 min), atualização automática, gravação de amostras e reconectar.

## Detecção

Random Forest (200 árvores) treinado offline no SisFall a 100 Hz, ±8 g / ±2000 °/s, validado por
voluntário: 98,8 % das quedas detectadas e 95,3 % de especificidade (limiar 0,5). Detalhes em
`modelos/resultado_treino_mvp_8g.txt`. O modelo não aprende em uso; para incorporar novos dados é
preciso retreinar. Entre dois alarmes do mesmo cinto há um silêncio de 5 s.

## Localização

Estimativa por RSSI das 3 antenas (modelo log-distância), mediana de 4 s, histerese de 0,6 m,
confirmação de 3 s para troca de quadrante e retenção da última posição válida por até 6 s com
baixa confiança. O mapa desenha um círculo por antena com o raio estimado.

Limite conhecido e medido (`dados/ensaios_rssi/RESULTADO_1m.txt`): com o cinto na frente do corpo,
o tronco atenua ~22 dB para a antena às costas e ~12 dB lateralmente, mais do que a sala inteira
(14 dB em 5 m). Subir as antenas não reduziu esse efeito. A trilateração deve ser lida como
estimativa de região/quadrante, não de ponto. Próximo passo planejado: estimar posição e orientação
usando o padrão de sombreamento medido.

## Banco de dados

SQLite em `dados/oqpnb.db`. Janelas, quedas e status das antenas são gravados sempre; amostras
brutas só enquanto "Gravar amostras" estiver ligado. Modelagem completa (DER, lógico, físico,
dicionário de dados) em `docs/banco_de_dados.md`. A aba Detalhes exporta CSV por sessão e o próprio `.db`.
