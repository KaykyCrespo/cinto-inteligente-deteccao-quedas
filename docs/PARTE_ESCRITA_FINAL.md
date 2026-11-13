# PARTE ESCRITA DO TCC — INOVAÇÃO FRUGAL APLICADA À TECNOLOGIA ASSISTIVA

## Situação do documento

**Versão preparatória — levantamento inicial, evidências e planejamento. Data: 12/11/2026; atualizada em 13/11/2026.**

O nome `PARTE_ESCRITA_FINAL` identifica o arquivo de trabalho solicitado, não uma versão científica concluída ou pronta para entrega. Não foi redigida a introdução, não foram reformulados objetivos ou hipóteses e não se iniciou a redação dos capítulos. A leitura dos seis materiais indicados pelo orientador foi autorizada e está registrada na Seção 9. O posicionamento e a redação dos capítulos dependem de aprovação, conforme o protocolo fornecido.

A inovação frugal constitui a perspectiva central desta investigação. A pergunta orientadora da concepção é identificar os recursos mínimos necessários para atender à necessidade essencial, sem comprometer segurança, qualidade ou adequação ao usuário. Isso é uma diretriz de investigação, não uma conclusão de que o protótipo já seja frugal, economicamente viável ou superior a alternativas comerciais.

O enquadramento institucional na vertente SmartCity pode ser mantido como contexto da aplicação. A inovação frugal deverá orientar as decisões de concepção, a comparação de arquiteturas, a análise econômica e a discussão dos resultados, sem ser reduzida à compra de componentes de menor preço.

**Referência econômica aprovada pela equipe em 13/11/2026:** um cinto e uma antena, sem AD8232, cabo de ECG ou eletrodos, com a infraestrutura necessária ao funcionamento da arquitetura atual. A configuração experimental ampliada será analisada separadamente. A aprovação define a referência de análise; não equivale a validação experimental.

**Decisões da equipe registradas em 13/11/2026:** o alerta remoto pelo Telegram é requisito essencial, de modo que o acesso à internet integra a referência mínima; a chave gangorra deve ficar entre o TP4056 e o MT3608, como nas tabelas do manual; a declaração de uso de IA foi retirada do manual e está no Apêndice B, ao final deste documento; os vídeos de testes serão hospedados em drive externo; as fotografias da montagem, da medição com multímetro e dos cases reais do cinto e da antena foram reservadas para a parte escrita e não constam no manual; a seção de pendências de validação foi retirada do manual, e as pendências seguem na Seção 7 deste documento. Os preços unitários de doze itens, informados pela equipe, foram lançados na planilha de custos, sem registro de fornecedor ou data. A fonte USB de recarga fica fora do custo, porque o usuário utiliza um carregador de celular próprio.

## 1 Resumo técnico do sistema real

O protótipo utiliza ESP32-C3 no cinto e MPU6050 para aquisição de aceleração e velocidade angular, com configuração nominal de 100 Hz, ±8 g e ±2000 °/s. Na implementação ampliada, o cinto também lê o sinal analógico do AD8232 e os indicadores de eletrodos desconectados. O firmware examinado não calcula frequência cardíaca em BPM.

Uma antena ESP32 DevKit V1 se conecta ao cinto por GATT, recebe os dados dos sensores e os encaminha por Wi-Fi de 2,4 GHz e MQTT. As demais antenas recebem anúncios BLE e fornecem RSSI. Não se deve descrever Advertising como transporte do fluxo inercial rápido desta versão.

No computador central, o backend constrói janelas de 2,5 s, com passo de 0,5 s, calcula oito atributos inerciais e executa um Random Forest. A decisão indica possível queda, não diagnóstico clínico. O processamento não utiliza ECG ou localização como entradas do classificador. O dashboard apresenta dados e alertas, e a persistência utiliza SQLite, não MySQL.

A notificação pelo Telegram é um recurso implementado, condicionado a credenciais, habilitação, conectividade e disponibilidade de serviço externo. A presença de processamento local não torna todo o sistema independente da internet quando esse alerta remoto é utilizado.

**Base de verificação:** firmware do cinto e das antenas, `features.py`, `detector_queda.py`, `interface.py`, `localizacao.py`, `banco.py`, manual e relatório de treinamento. O levantamento foi dirigido aos módulos centrais e às evidências disponíveis; não constitui auditoria integral de todas as bibliotecas, vídeos ou arquivos do repositório.

## 2 Inventário inicial de evidências

**Quadro 1 – Evidências encontradas e limites de interpretação**

| Material | Localização no repositório | Evidência disponível | Limite |
|---|---|---|---|
| Firmware do cinto | `Arduino/cinto_mvp_v1/cinto_mvp_v1.ino` | Aquisição inercial, leitura de ECG bruto e envio GATT | Não demonstra autonomia, segurança elétrica ou funcionamento sem ECG |
| Firmware da antena | `Arduino/anchor_mvp_v1/anchor_mvp_v1.ino` | Recepção BLE e comunicação MQTT | Presença de código não comprova disponibilidade contínua ou alcance |
| Extração e inferência | `features.py`, `detector_queda.py` | Classificação baseada em seis eixos inerciais | Não comprova generalização clínica ou probabilidade de risco calibrada |
| Treinamento | `scripts/treino_sisfall.py` | GroupKFold por voluntário e avaliação por ensaio | Não apresenta comparação experimental com regra de limiar |
| Relatório de treinamento | `modelos/resultado_treino_mvp_8g.txt` | 4.505 ensaios; VP 1.777, FN 21, FP 128, VN 2.579 | Não é avaliação exclusiva da configuração mínima em bancada |
| Modelo e gráficos | `modelos/modelo_mvp_8g.joblib`, `docs/esquemas/` | Artefato treinado e representação dos resultados | O modelo não foi retreinado nesta etapa |
| Persistência | `banco.py`, `dados/README_BANCO_DE_DADOS.md` | Esquema SQLite com sete tabelas | O esquema não comprova implantação ou registros de todos os ensaios |
| Localização | `localizacao.py` | Estimativa por referências múltiplas e filtros de consistência | Uma antena não produz coordenadas validadas |
| Ensaios RSSI | `dados/ensaios_rssi/RESULTADO_ENSAIOS_RSSI.txt` e oito CSVs | Comparação exploratória de 1, 2, 3, 5 e 7 m e alternância GATT a 1 m | Não monotonicidade e condições geométricas a confirmar |
| Testes automatizados | `tests/teste_localizacao.py`, `tests/teste_alerta_telegram.py` | Casos de lógica de localização e de alerta | Testes de software não substituem ensaios físicos; não foram executados nesta etapa |
| Vídeos próprios | `dados/testes/` | Quatro arquivos identificados no manual | Conteúdo e associação com CSV/horário/evento não conferidos integralmente |
| Fotografias e esquemas | `docs/esquemas/esquemas eletricos/`, `docs/IMAGENS/Case Cinto/`, `docs/IMAGENS/Case Antena/` | Registros de montagem e de medição, dez fotografias dos cases reais e diagramas; as fotografias serão usadas na parte escrita | Posição da chave divergente entre figuras e tabelas; visor do multímetro ilegível na foto, que não comprova os valores; as fotos dos cases não permitem conferir a ligação elétrica da chave |
| Projetos de impressão | `docs/impressao_3d/Case Cinto.3mf` e `Case Antena.3mf` | Arquivos de fabricação dos cases | Não há orçamento comprovado de material, impressão ou mão de obra |
| Manual e apoios | `docs/MANUAL/`, `docs/APOIO/` | Procedimentos e requisitos de entrega | A parte escrita antiga contém descrições de arquitetura desatualizadas |

Fonte: Elaborado pelos autores (2026), a partir do levantamento inicial do repositório.

As métricas do relatório são: sensibilidade 98,8%, precisão 93,3%, F1-score 96,0%, especificidade 95,3% e acurácia 96,7%. São agregadas por ensaio dos voluntários de teste. Um ensaio é positivo se qualquer janela atingir o limiar; esses valores não medem atraso de detecção ou falsos alarmes por hora e não validam a aplicação clínica.

Os vídeos identificados são `Vídeo Andando perto da 3 Anchors.mp4`, `Vídeo Sentando perto das 3 Anchor.mp4`, `Caindo.mp4` e `Deitando e Caindo.mp4`. Seus títulos não devem ser utilizados como prova de classificação correta. A comprovação de cada teste exige conferência de conteúdo, horário, CSV e evento do sistema.

## 3 Configuração experimental ampliada

**Quadro 2 – Caracterização da configuração ampliada**

| Dimensão | Configuração documentada | Estágio ou ressalva |
|---|---|---|
| Unidade corporal | Um cinto com ESP32-C3 e MPU6050 | Arquitetura descrita no firmware e no manual |
| ECG | AD8232, cabo e três eletrodos | Aquisição de sinal bruto; qualidade e utilidade não validadas clinicamente |
| Comunicação | Uma antena GATT e outras duas com Advertising/RSSI | Três antenas fazem parte do arranjo experimental, não automaticamente do custo mínimo |
| Localização | RSSI de três referências para estimativa espacial | Condições de calibração e erro contra referência ainda pendentes |
| Processamento | Computador, broker, backend e dashboard | Necessários na arquitetura efetivamente implementada |
| Persistência | SQLite e arquivos de amostras | Rastreabilidade prevista pelo software |
| Alerta | Dashboard e Telegram quando habilitado | Entrega depende da infraestrutura; latência ponta a ponta não medida |

Fonte: Elaborado pelos autores (2026).

O ECG e a localização multirreferência serão tratados como extensões experimentais. O fato de terem sido desenvolvidos e integrados não permite classificá-los como indispensáveis à detecção inercial nem como funcionalidades plenamente validadas.

## 4 Configuração mínima de referência: um cinto e uma antena, sem ECG

A referência proposta preserva ESP32-C3, MPU6050, uma antena ESP32 DevKit V1 para BLE/MQTT, computador central, rede Wi-Fi, alimentação, encapsulamento, processamento e apresentação do alerta. Não pressupõe transferir a inferência para o cinto, retirar o computador, reduzir baterias ou alterar a alimentação, pois essas mudanças não foram implementadas ou validadas nesta etapa.

AD8232, cabo de ECG e eletrodos ficam fora da referência econômica. A localização por trilateração também fica fora: com uma única medida de distância a uma referência conhecida, não se determina de forma única uma posição bidimensional. O círculo de distância estimada não é uma coordenada do usuário; além disso, a própria conversão RSSI-distância requer validação.

Em `localizacao.py`, a estimativa bruta retorna `None` com menos de duas antenas, e a rotina de posição consistente exige pelo menos três leituras recentes. Uma posição anterior pode ser retida temporariamente com baixa confiança; isso não é uma nova medição feita com uma antena. O RSSI de uma antena pode informar intensidade recebida e, eventualmente, apoiar uma classificação de proximidade após ensaio específico, mas não há comprovação dessa funcionalidade de proximidade nesta etapa.

**Restrição de implementação:** o firmware atual continua lendo os pinos de ECG e estado dos eletrodos. Retirar fisicamente o módulo não equivale a disponibilizar um modo de operação sem ECG: é preciso decidir como desabilitar essas leituras, representar sensor ausente no pacote e na interface, evitar estados falsos e testar o fluxo completo. Não houve alteração de código ou hardware para executar essa proposta.

**Requisito assistivo definido pela equipe:** o alerta remoto pelo Telegram é essencial. Por isso, o acesso à internet, as credenciais do bot e a disponibilidade do serviço externo integram a referência mínima e seus custos. O painel local permanece como interface de acompanhamento e diagnóstico e é o processo que executa o backend. A entrega e o atraso do alerta ainda não foram medidos.

## 5 Matriz de funcionalidades essenciais e complementares

As classificações abaixo são propostas para validação dos requisitos com a equipe e o orientador, não necessidades de usuários empiricamente comprovadas.

**Quadro 3 – Funcionalidade, essencialidade e configuração**

| Funcionalidade ou recurso | Classificação proposta | Referência mínima | Configuração ampliada | Evidência e decisão pendente |
|---|---|---|---|---|
| Aquisição inercial | Essencial à abordagem adotada | ESP32-C3 e MPU6050 | Mesmos componentes | Implementada; testar uso da referência mínima |
| Transporte dos sensores | Essencial | Uma antena GATT e MQTT | Uma antena GATT entre três unidades | Fluxo implementado; medir perdas, alcance e disponibilidade |
| Classificação de possível queda | Essencial | Random Forest no computador | Mesmo classificador | Métricas no SisFall; validação própria separada necessária |
| Alerta visual ao responsável | Apoio ao alerta remoto; o painel também executa o backend | Dashboard | Dashboard | Definir presença e resposta do operador |
| Notificação remota | Essencial (definido pela equipe em 13/11/2026) | Telegram, com internet | Telegram implementado | Medir entrega e atraso do alerta ponta a ponta |
| Computador e broker | Essenciais na arquitetura atual | Mantidos | Mantidos | Não demonstrado funcionamento autônomo somente no cinto |
| Wi-Fi e roteador | Essenciais na arquitetura atual | Mantidos | Mantidos | Infraestrutura existente também tem uso e manutenção atribuíveis |
| Persistência e registro de eventos | Essencial ao escopo de rastreabilidade adotado | SQLite mantido | SQLite mantido | Eventual simplificação exige decisão de requisito, não remoção automática |
| ECG bruto | Complementar experimental | Ausente | AD8232 e eletrodos | Não integra os atributos de classificação; modo sem sensor precisa ser implementado/testado |
| Frequência cardíaca em BPM | Não implementada no firmware examinado | Não prometer | Não prometer | Parte escrita antiga deve ser atualizada |
| Trilateração e quadrantes | Complementar experimental | Não disponível | Três referências com geometria adequada | Não prometer precisão; testar contra posições de referência |
| Proximidade por RSSI | Candidata complementar | Pode ser investigada, não validada | RSSI disponível | Definir classes e aferir resultados antes de alegar detecção de proximidade |
| Duas antenas adicionais | Complementares à comunicação básica; necessárias ao arranjo de localização estudado | Ausentes | Presentes | Benefício espacial deve justificar recursos adicionais |
| Eletrodos e indicação de desconexão | Complementares ao ECG | Ausentes ou indicação explícita de não aplicável | Presentes | Não apresentar falta do módulo como falha de uso do cinto mínimo |
| Alimentação protegida e encapsulamento | Essenciais | Mantidos | Mantidos | Confirmar circuito, recarga, isolamento e segurança; não reduzir proteções por preço |

Fonte: Elaborado pelos autores (2026), como matriz preliminar de requisitos.

## 6 Planilha comparativa e análise preliminar de custos

A planilha [PARTE_ESCRITA_FINAL_CUSTOS.csv](PARTE_ESCRITA_FINAL_CUSTOS.csv) utiliza separador ponto e vírgula e contém 36 itens, com categoria, unidade, classificação, quantidade mínima proposta, quantidade ampliada da BOM, preço unitário, subtotais, fonte, data e observações. A equipe informou os preços unitários de doze itens, lançados na planilha. Por decisão da equipe, a planilha não registra fornecedor nem data de compra. Os demais campos monetários continuam em branco. Campo vazio significa **não informado**, nunca custo nulo.

As quantidades da configuração ampliada são referências da BOM do manual, não auditoria física de estoque. Quantidades da configuração mínima são propostas. Itens cuja quantidade ainda não foi definida, como o capacitor e os fios da configuração ampliada, permanecem sem quantidade numérica. Segundo a equipe, o valor do AD8232 inclui o cabo e os eletrodos, e o valor dos cases inclui o material de impressão.

**Tabela 1 – Situação da estimativa econômica**

| Grandeza | Situação inicial | Dados necessários |
|---|---|---|
| Custo mínimo: um cinto e uma antena, sem ECG | R$ 250,79 em componentes e cases; infraestrutura e montagem não incluídas | Capacitor, cinto têxtil, infraestrutura, energia e montagem |
| Custo ampliado: um cinto, três antenas e ECG | R$ 497,67 em componentes e cases, sem os fios; infraestrutura e montagem não incluídas | Fios da configuração ampliada e os mesmos itens da linha anterior |
| Custo incremental das extensões | R$ 249,38 entre os itens com preço nas duas configurações | Fios da configuração ampliada |
| Custo de reprodução | Não calculável | Materiais, fabricação, configuração, frete, tributos e mão de obra |
| Custo de operação e manutenção | Não calculável | Energia, internet atribuível, reposição, suporte e horizonte temporal |
| Eventual preço comercial | Não estimado | Certificação, embalagem, garantia, suporte, escala e margem |

Fonte: Elaborado pelos autores (2026).

**Tabela 2 – Preços informados pela equipe e subtotais de componentes e cases**

| Item | Preço unitário (R$) | Qtd. mínima | Subtotal mínimo (R$) | Qtd. ampliada | Subtotal ampliado (R$) |
|---|---|---|---|---|---|
| ESP32-C3 Super Mini | 55,00 | 1 | 55,00 | 1 | 55,00 |
| ESP32 DevKit V1 | 49,99 | 1 | 49,99 | 3 | 149,97 |
| MPU6050 (GY-521) | 30,00 | 1 | 30,00 | 1 | 30,00 |
| Bateria 18650 | 12,90 | 3 | 38,70 | 5 | 64,50 |
| TP4056 | 7,90 | 2 | 15,80 | 4 | 31,60 |
| MT3608 | 10,00 | 2 | 20,00 | 4 | 40,00 |
| Chave gangorra | 1,90 | 2 | 3,80 | 4 | 7,60 |
| Case do cinto | 20,00 | 1 | 20,00 | 1 | 20,00 |
| Case da antena | 10,00 | 1 | 10,00 | 3 | 30,00 |
| Parafusos (3 no cinto, 2 por antena) | 1,00 | 5 | 5,00 | 9 | 9,00 |
| Fios (conjunto de 2 m) | 2,50 | 1 | 2,50 | Não informada | Não calculado |
| AD8232 com cabo e eletrodos (ECG) | 60,00 | 0 | 0,00 | 1 | 60,00 |
| **Subtotal** |  |  | **250,79** |  | **497,67** |

Fonte: Elaborado pelos autores (2026), com preços informados pela equipe.

Na configuração mínima, o cinto sem ECG soma R$ 153,60 e a antena soma R$ 94,69; com os fios, o total é R$ 250,79. O preço dos parafusos foi informado como R$ 5,00 por cinco unidades, e aqui foi tratado como R$ 1,00 por parafuso; falta confirmar se ele inclui os insertos de latão. Entre os itens com preço nas duas configurações, a diferença de R$ 249,38 corresponde a duas antenas adicionais (R$ 189,38) e ao AD8232 (R$ 60,00).

Os subtotais da Tabela 2 cobrem componentes e cases, não o custo completo de nenhuma das configurações. Ficam de fora o capacitor de 470 µF, o cinto têxtil, os cabos USB de gravação e os fios da configuração ampliada, além de computador, roteador, internet, energia e tempo de montagem. A fonte USB de recarga não entra no custo, por decisão da equipe.

Quando houver dados, calcular os subtotais como quantidade multiplicada pelo preço unitário de cada item. O total de uma configuração deve incluir a fronteira de custos explicitamente adotada, e não apenas os componentes eletrônicos. Comparar $C_{ampliada} - C_{minima}$ somente sob fontes, datas e critérios equivalentes. Não gerar totais parciais com aparência de orçamento completo.

Considerar dois cenários de infraestrutura: aquisição de computador/roteador e aproveitamento de equipamentos já disponíveis. No segundo caso, separar desembolso incremental de custo atribuível de uso, energia e manutenção. Software sem cobrança de licença também exige confirmação de licenças e não elimina custos de implantação e suporte.

**Constatação estrutural, não econômica:** a proposta reduz de três para uma antena, retirando duas unidades. Isso corresponde a 66,7% das antenas ou 50% dos nós embarcados quando se contam apenas um cinto e as antenas (quatro nós para dois). Esses percentuais não representam economia de custo, energia total ou infraestrutura. Os dois cenários ainda dependem do computador e do roteador atuais.

### 6.1 Matriz de comparação com soluções existentes

**Quadro 4 – Estrutura da comparação comercial a realizar**

| Família de solução a pesquisar | Funcionalidade a conferir | Custos a levantar | Cuidado de comparabilidade |
|---|---|---|---|
| Relógio com detecção automática de quedas | Detecção, acionamento, comunicação e limites de uso | Equipamento, telefone exigido, plano e manutenção | Distinguir funções anunciadas de avaliações independentes |
| Dispositivo de alerta para cuidador | Automático ou botão manual, serviço e resposta | Equipamento, assinatura e infraestrutura | Botão manual não equivale a detecção automática |
| Vestível ou cinto de monitoramento | Sensores, detecção e contexto de aplicação | Aquisição e implantação documentadas | Comparar o mesmo conjunto essencial de funções |
| Sistema de localização/monitoramento indoor | Cobertura, referências e erro de localização | Sensores, instalação, servidor e operação | Comparar separadamente com a configuração ampliada |

Fonte: Elaborado pelos autores (2026), como roteiro de levantamento, sem produtos ou preços presumidos.

A matriz final deverá identificar produto, fabricante, fonte e data do preço, moeda, sensores, infraestrutura, funções, manutenção e limitações. Se o preço não for público ou não for localizado, registrar essa ausência. Comparações em moedas distintas exigem taxa, fonte e data; não converter informalmente. Não comparar o custo de materiais do protótipo com preço de produto comercial como se fossem grandezas equivalentes.

## 7 Lacunas e limitações que exigem confirmação

- Definir a disponibilidade e o tempo de resposta esperados para o alerta remoto, já definido como essencial.
- Realizar ensaio específico com um cinto e uma antena, sem ECG; separar viabilidade conceitual de operação validada.
- Redesenhar no Fritzing as Figuras 5 e 6 do manual: elas mostram a chave após o MT3608, e a equipe definiu que ela fica entre o TP4056 e o MT3608. Continuam pendentes a conferência na montagem física e o funcionamento da proteção, da recarga e do isolamento. A frugalidade não pode justificar redução de segurança.
- Completar os custos que faltam (lista após a Tabela 2): capacitor, cinto têxtil, cabos USB, infraestrutura, energia e montagem. Confirmar se o preço dos parafusos inclui os insertos.
- Medir corrente média e de pico, autonomia, recarga e temperatura do cinto e da antena e identificar os reguladores das placas. Os valores do manual são hipóteses de dimensionamento, não medições.
- Medir energia do sistema completo, incluindo computador e roteador. Retirar dois nós não comprova a mesma redução percentual no consumo total.
- Medir latência, perdas e indisponibilidade. A versão atual do firmware não transmite contador de sequência; a quantificação de perdas exige cuidado metodológico.
- Associar vídeos a CSVs, horários, eventos e configuração; distinguir demonstração visual de avaliação quantitativa.
- Avaliar o classificador com dados próprios rotulados e comparar com limiares sob o mesmo protocolo. Não reutilizar as métricas do SisFall como validação de todo o protótipo mínimo.
- Confirmar o erro de localização na configuração ampliada. Os ensaios RSSI recentes não sustentam calibração confiável.
- Avaliar utilidade, conforto, manutenção e necessidade de capacitação do operador. Não afirmar adequação a idosos sem evidência pertinente.
- Conciliar parte escrita, manual e apresentação: MySQL/BPM/4 Hz/±2 g ainda aparecem no apoio antigo.
- Confirmar o manual institucional, os registros de uso das ferramentas de IA e a integridade das referências.

## 8 Relação das evidências com os três eixos da inovação frugal

**Quadro 5 – Eixos, indícios e critérios de verificação**

| Eixo | Indício inicial no projeto | O que ainda precisa ser demonstrado | Métricas propostas, sujeitas à aprovação |
|---|---|---|---|
| Redução de recursos | Referência com uma antena e sem módulo/eletrodos de ECG; processamento local existente | Custo e energia reduzidos sem perda essencial ou transferência oculta de custo | Quantidade de componentes, nós, custo de reprodução, potência média/pico e consumo por período |
| Simplicidade funcional | Separação entre detecção inercial e extensões de ECG/localização | Menor complexidade de montagem/operação e funções essenciais mantidas | Etapas e tempo de montagem/configuração, manutenção, erros operacionais e rastreabilidade |
| Acessibilidade e viabilidade | Componentes e projetos de case identificados; potencial de reprodução | Preços, disponibilidade, custo total, suporte e adequação ao responsável e usuário | Custo inicial e recorrente, disponibilidade local, necessidade de pessoal técnico e avaliação de uso |

Fonte: Elaborado pelos autores (2026), como proposta de operacionalização da investigação.

Redução de componentes é um indício mensurável, não definição suficiente de inovação frugal. A análise deverá mostrar quais benefícios essenciais permanecem, para quem são adequados e sob quais limites de segurança e desempenho. IA não é incompatível com frugalidade por ser sofisticada: sua inclusão precisa ser justificada por benefício proporcional a custo, infraestrutura e complexidade, com comparação pertinente.

## 9 Pesquisa bibliográfica

Os seis materiais indicados pelo orientador foram consultados em 13/11/2026. Três foram lidos no texto integral, dois apenas no resumo e um apenas nos metadados, como mostra o Quadro 6. A leitura foi feita por extração automática das páginas; conferir cada dado no original antes de citar.

**Quadro 6 – Materiais indicados pelo orientador e acesso obtido**

| Identificador | Publicação | Endereço indicado | Acesso obtido |
|---|---|---|---|
| B01 | Fritz et al. (2026), JMIR Aging | <https://aging.jmir.org/2026/1/e88290> | Texto integral |
| B02 | Fuentes et al. (2021), Sensors | <https://www.mdpi.com/1424-8220/21/18/6051> | Texto integral, pelo Europe PMC |
| B03 | Azevedo Antunes e Brito Palma (2026), Electronics | <https://www.mdpi.com/2079-9292/15/16/3669> | Resumo e metadados |
| B04 | Rafee, Zishan e Noor (2026), Journal of Systems Architecture | <https://www.sciencedirect.com/science/article/abs/pii/S1383762126001141> | Apenas metadados; a página exige autenticação |
| B05 | Vargas et al. (2024), Sensors | <https://pmc.ncbi.nlm.nih.gov/articles/PMC11397814/> | Texto integral, pelo Europe PMC |
| B06 | Fernandes (2026), TCC do IFMG | <https://repositorio.ifmg.edu.br/items/a8c31f0a-d1c3-4f66-8d62-45a40199959a> | Resumo e metadados; o PDF não foi lido |

Fonte: Elaborado pelos autores (2026), a partir dos endereços fornecidos pelo orientador.

### 9.1 B01 — Fritz et al. (2026)

- **Referência:** FRITZ, R. L. et al. A community-in-the-loop approach to smart home monitoring for aging in place: mixed methods evaluation of a co-designed prototype. **JMIR Aging**, v. 9, e88290, 2026. DOI: 10.2196/88290.
- **Objetivo:** avaliar barreiras e facilitadores à adoção de uma casa inteligente de baixo custo, apoiada por uma rede comunitária, por idosos com várias condições crônicas e em situação de pobreza.
- **Método:** estudo prospectivo de métodos mistos com co-design comunitário. Foram monitorados 48 participantes de 54 a 94 anos, por até seis meses, com seis multissensores de ambiente por casa. Alertas gerados por regras eram escalonados do participante à pessoa de apoio, ao agente comunitário de saúde e ao enfermeiro.
- **Resultados:** o sistema gerou 4.719 alertas. Os participantes responderam a 1,57% dos e-mails e a 7,79% dos SMS; agentes comunitários e enfermeiros responderam a 78,36% dos alertas escalonados. Em 93% dos alertas nenhuma ação foi necessária. A nota média de recomendação foi 8,68 em 10 (n = 33), mas os participantes preferiram ligação telefônica ao alerta automático. A meta de menos de US$ 400 de hardware por casa foi cumprida; os autores registram custos adicionais de pessoal, treinamento, suporte técnico e conectividade.
- **Limitações:** amostra pequena e específica; protótipo alterado durante o estudo; regras fixas geraram alertas irrelevantes ou perdidos; a dependência de equipe humana limita a escala. O sistema não se destinava a detectar emergências.
- **Relação com a pesquisa:** não trata de detecção de quedas nem de vestíveis. Apoia três pontos do TCC: o custo real vai além do hardware; a internet pode ser barreira para idosos de baixa renda; e a resposta a alertas automáticos por mensagem foi baixa, o que pesa na decisão de tratar o Telegram como canal essencial.

### 9.2 B02 — Fuentes et al. (2021)

- **Referência:** FUENTES, D. et al. IndoorCare: low-cost elderly activity monitoring system through image processing. **Sensors**, v. 21, n. 18, 6051, 2021. DOI: 10.3390/s21186051.
- **Objetivo:** propor uma solução acessível e não intrusiva para acompanhar as atividades de idosos em casa, preservando a privacidade.
- **Método:** um Raspberry Pi Zero W com câmera olho de peixe por cômodo detecta movimento com OpenCV no próprio dispositivo. Um gateway com VPN leva os dados a um servidor Raspberry Pi 3 B, que mostra ao cuidador uma linha do tempo dos eventos.
- **Resultados:** protótipo funcional, testado em ambiente simulado. Os autores informam cerca de EUR 45 por dispositivo de monitoramento, EUR 50 pelo servidor e EUR 30 pelo gateway, sem IVA. Cinco pessoas no papel de cuidador interpretaram a linha do tempo; duas confundiram dois eventos parecidos.
- **Limitações:** não houve testes com idosos, por causa da pandemia; o sistema não detecta quedas nem emite alertas automáticos, deixados como trabalho futuro; os autores recomendam um servidor mais robusto em uso real.
- **Relação com a pesquisa:** exemplo de argumentação de baixo custo com preço por dispositivo e separação entre dispositivo, gateway e servidor, a mesma fronteira de custos que o TCC precisa definir. Usa câmera, em contraste com o vestível deste projeto.

### 9.3 B03 — Azevedo Antunes e Brito Palma (2026)

- **Referência:** AZEVEDO ANTUNES, R.; BRITO PALMA, L. A new hardware/software assistive Wi-Fi device for elderly bed-exit event at night. **Electronics**, v. 15, n. 16, 3669, 2026. DOI: 10.3390/electronics15163669.
- **Objetivo (resumo):** alertar o cuidador quando o idoso sai da cama à noite e acender a luz do quarto, para prevenir quedas.
- **Método (resumo):** sensor infravermelho passivo de movimento, sensor de luz e hardware com ESP32-C6, que se comunica por Wi-Fi com um aplicativo Android do cuidador.
- **Resultados (resumo):** os autores descrevem o sistema como de baixo custo, sem bateria, sem necessidade de contrato de internet e com preservação da privacidade. O resumo não traz valores de custo nem de desempenho.
- **Limitações:** não constam no resumo.
- **Relação com a pesquisa:** trata de prevenção, não de detecção, e não é vestível. Interessa por dispensar internet e bateria, duas dependências que a configuração mínima deste projeto mantém. A lista de referências do artigo inclui produtos comerciais de detecção de quedas, que podem servir de ponto de partida para a comparação da Seção 6.1.

### 9.4 B04 — Rafee, Zishan e Noor (2026)

- **Referência:** RAFEE, A. N. M.; ZISHAN, M. A. O.; NOOR, J. Decision tree-based real-time personalized human activity recognition and fall detection utilizing cost effective highly resource-constrained microcontrollers. **Journal of Systems Architecture**, v. 176, 103796, 2026. DOI: 10.1016/j.sysarc.2026.103796.
- **Objetivo, método, resultados e limitações:** não lidos. Foram obtidos apenas título, autores, periódico e lista de referências.
- **Relação com a pesquisa:** pelo título, o artigo trata de reconhecimento de atividades e detecção de quedas com árvores de decisão em microcontroladores de baixo custo. Pode apoiar a escolha de um modelo baseado em árvores e a discussão sobre processar no próprio dispositivo. Não citar antes da leitura do texto.

### 9.5 B05 — Vargas et al. (2024)

- **Referência:** VARGAS, V.; RAMOS, P.; ORBE, E. A.; ZAPATA, M.; VALENCIA-ARAGÓN, K. Low-cost non-wearable fall detection system implemented on a single board computer for people in need of care. **Sensors**, v. 24, n. 17, 5592, 2024. DOI: 10.3390/s24175592.
- **Objetivo:** propor um sistema acessível e não vestível de detecção de quedas para pessoas que precisam de cuidados.
- **Método:** visão computacional com o modelo SSD-MobileNet-v2 em um Raspberry Pi 4 com câmera HD de filtro IR-CUT. O sistema classifica cinco posturas e envia alerta com foto pelo Telegram. O treinamento usou 27.649 imagens. A avaliação teve 14 participantes de 26 a 84 anos e 756 testes, variando roupa, iluminação e distância.
- **Resultados:** precisão de 96,4%, especificidade de 96,6%, acurácia de 94,8%, sensibilidade de 93,1% e AUC de 0,957. Os autores informam custo de cerca de US$ 150. Dos falsos negativos, 81% ocorreram a mais de 3 m da câmera.
- **Limitações:** o alerta depende de internet; o desempenho cai com distância acima de 3 m, pouca luz e roupa escura; o uso de câmera levanta questões de privacidade.
- **Relação com a pesquisa:** é o material mais próximo do TCC na estrutura do argumento: baixo custo declarado, alerta pelo Telegram, métricas de classificação e testes com pessoas em condições controladas. Serve de modelo para o desenho dos testes próprios. Os autores também apontam fraquezas dos vestíveis, como depender de o usuário vestir o aparelho e de bateria, que o TCC precisa discutir.

### 9.6 B06 — Fernandes (2026)

- **Referência:** FERNANDES, T. S. **Nexar**: sistema de detecção de queda de baixo custo para idosos. 2026. Trabalho de Conclusão de Curso (Bacharelado em Sistemas de Informação) – Instituto Federal de Minas Gerais, Ouro Branco, 2026. Disponível em: https://hdl.handle.net/20.500.14387/3000.
- **Objetivo (resumo):** propor um sistema de detecção automática de quedas com dispositivo vestível de baixo custo, baseado em ESP32 e sensor inercial de seis eixos.
- **Método (resumo):** arquitetura em três camadas: pré-processamento no dispositivo, API REST em Spring Boot e classificação em Python com redes CNN e LSTM. Um aplicativo móvel emite alertas e registra a localização pelo GPS do celular.
- **Resultados (resumo):** o resumo fala em resultados esperados, como maior precisão e menos alarmes indevidos, e não traz valores.
- **Limitações:** não constam no resumo.
- **Relação com a pesquisa:** é o trabalho brasileiro mais parecido em hardware. Difere por usar redes neurais e aplicativo móvel, enquanto este projeto usa Random Forest e Telegram. A leitura do PDF é prioritária para comparar custo, métricas e arquitetura.

### 9.7 Síntese parcial

Nos textos e resumos lidos, o termo inovação frugal não aparece. Os seis materiais tratam de baixo custo, acessibilidade e restrição de recursos, e nenhum deles fundamenta sozinho a tese do trabalho. A fundamentação do eixo frugal depende da busca complementar descrita a seguir.

Três materiais trazem custo declarado: B01 (menos de US$ 400 de hardware por casa), B02 (cerca de EUR 45 por dispositivo, EUR 50 pelo servidor e EUR 30 pelo gateway) e B05 (cerca de US$ 150). São protótipos de escopo, moeda e ano diferentes; não comparar com o custo deste projeto sem conversão documentada e sem igualar a fronteira de custos.

Falta ler o texto integral de B03, B04 e B06.

Complementar com literatura científica sobre critérios de inovação frugal, adequação funcional, custo total e tecnologias assistivas. Proposta de busca: combinar termos como `frugal innovation`, `assistive technology`, `older adults`, `fall detection`, `resource constraints`, `total cost` e equivalentes em português, em bases científicas e repositórios institucionais. Definir período, critérios de inclusão/exclusão e registro das buscas antes de executar a revisão. Separar artigos, documentação de fabricantes, normas e páginas comerciais.

O acompanhamento de novas publicações deverá ocorrer em revisões datadas da busca durante a elaboração, não por uma promessa de monitoramento automático que ainda não foi configurado.

## 10 Estrutura recomendada do TCC

Esta é uma proposta de estrutura para validação, não capítulos redigidos. A numeração e os elementos pré-textuais serão ajustados ao manual institucional aplicável.

**Quadro 7 – Capítulos e papel da inovação frugal**

| Capítulo proposto | Conteúdo a elaborar após aprovação | Evidências necessárias |
|---|---|---|
| 1 Introdução | Problema assistivo, necessidade de acessibilidade, justificativa frugal, objetivos, delimitação e contribuição | Literatura de contexto e definição do requisito essencial; introdução ainda não redigida |
| 2 Fundamentação teórica | Inovação frugal como eixo central, tecnologia assistiva, sensores, IoT, IA e trabalhos relacionados | Fichamentos dos indicados e literatura específica de frugalidade |
| 3 Metodologia | Configurações separadas, variáveis, protocolos, métricas técnicas/econômicas e critérios de aceitação | Protocolo aprovado, fronteira de custos e referências de teste |
| 4 Engenharia de software e desenvolvimento | Requisitos, arquitetura real, hardware, firmware, comunicação, backend, IA, SQLite e dashboard | Código e diagramas reconciliados; justificativas de recursos essenciais/adicionais |
| 5 Resultados | Mínima e ampliada separadas; custos, testes e limites | Dados e preços comprovados; sem misturar expectativa e resultado |
| 6 Análise e discussão | Recursos reduzidos, simplicidade, adequação, comparação econômica e confronto com literatura | Comparação sob critérios equivalentes e limitações explícitas |
| 7 Conclusão e trabalhos futuros | Resposta à questão aprovada, objetivos alcançados, contribuição frugal e limites | Síntese sustentada pelos resultados, sem validação integral presumida |

Fonte: Elaborado pelos autores (2026), a partir do protocolo de estrutura fornecido.

## 11 Apêndices e normalização: organização proposta

**Apêndice A — Manual do sistema desenvolvido:** reservar para a inserção integral do manual autoral, preservando sua finalidade operacional e atualizando sua identificação e paginação no conjunto do TCC. O [manual revisado](MANUAL/Manual_Usuario_Operacao_Revisado.pdf) é a fonte de trabalho atual; um link não substitui sua futura inclusão integral no apêndice.

**Apêndice B — Declaração de utilização de inteligência artificial:** a declaração foi retirada do manual em 13/11/2026 e está ao final deste documento. Faltam a conferência de ferramentas, versões, registros e percentuais e a assinatura dos integrantes.

**Ponto a confirmar com o orientador:** o apoio institucional de vídeo/manual pede a declaração de IA na Seção 4 do manual. Com a retirada da declaração e, depois, da seção de pendências, o manual não menciona mais a declaração nem o Apêndice B.

Materiais de autoria da equipe poderão ser apêndices adicionais; documentos de terceiros, quando pertinentes e autorizados, serão anexos. Utilizar **REFERÊNCIAS** para obras efetivamente citadas, sem inventar fontes. As obras indicadas em planejamento de busca não são referências automaticamente utilizadas no texto científico.

A conformidade integral com ABNT NBR 14724, 10520, 6023, 6024, 6027 e 6028 e com exigências específicas da UNIP depende da consulta às versões aplicáveis e ao manual institucional. Esta versão preparatória não constitui certificação de conformidade ou monografia normalizada para entrega.

## 12 Deliberações para avançar

1. Referência mínima de um cinto e uma antena, sem ECG: aprovada pela equipe em 13/11/2026.
2. Alerta remoto pelo Telegram: definido como essencial; faltam os limites aceitáveis de falha, atraso e resposta.
3. Modo sem ECG no firmware: pendente; nenhuma alteração de código foi feita.
4. Preços: doze itens informados; faltam capacitor, cinto têxtil, cabos USB, infraestrutura, energia e montagem. A pesquisa de preços de soluções comerciais comparáveis ainda não foi autorizada.
5. Fichamento dos seis materiais indicados: feito na Seção 9; faltam o texto integral de B03, B04 e B06 e a busca de literatura específica sobre inovação frugal.
6. Problema, objetivos, hipóteses e critérios de inovação frugal: validar somente depois dessas evidências, antes de redigir capítulos.
7. Declaração de IA: retirada do manual e transferida para o Apêndice B; falta confirmar o manual institucional de normalização.

Nenhuma conclusão sobre viabilidade econômica, eficácia clínica, localização com uma antena ou validação integral da configuração mínima foi estabelecida neste levantamento. O próximo avanço depende de aprovação da equipe, conforme o protocolo.

## Apêndice B — Declaração de utilização de inteligência artificial

Foram usadas ferramentas de IA generativa como apoio à documentação, à diagramação e ao código. O Quadro 8 preserva as informações declaradas pela equipe, sem tratá-las como comprovação independente. Os nomes de versões e os percentuais devem ser confrontados com os registros de uso antes da entrega. Nenhuma ferramenta é autora ou coautora do trabalho; a responsabilidade pela revisão, pela validação e pelo conteúdo final é dos integrantes. A declaração de ausência de dados pessoais ou sensíveis enviados às ferramentas também depende da conferência dos registros pela equipe.

**Quadro 8 – Uso declarado de ferramentas de IA assistiva e pendências de comprovação**

| Ferramenta | Versão e ambiente | Período | Finalidade | Intervenção humana |
|---|---|---|---|---|
| Claude (Anthropic) | Denominação informada: claude-opus-5-5; versão não confirmada | 14/09/2026 a 12/11/2026, conforme declaração da equipe | Organização do material, revisão e diagramas | Correção de 80% informada pela equipe; método de cálculo e registros não apresentados |
| Claude (Anthropic) | Denominação informada: Sonnet 4.6 low; versão não confirmada | 14/09/2026 a 12/11/2026, conforme declaração da equipe | Desenvolvimento web e firmware | Refatoração de cerca de 75% informada; método de cálculo e registros não apresentados |
| ChatGPT (OpenAI) | Denominação informada: ChatGPT 5.6 Sol extra alto; versão não confirmada | 14/10/2026 a 12/11/2026, conforme declaração da equipe | Desenvolvimento web e firmware | Refatoração de cerca de 75% informada; método de cálculo e registros não apresentados |
| GitHub Copilot | Assistente no VS Code; modelo não identificado | 09/11/2026 a 13/11/2026 | Revisão do manual, organização dos ensaios RSSI, gráficos de métricas, gerador de documentos e este documento preparatório, incluindo o fichamento dos artigos | Alterações sujeitas à aprovação e à revisão final dos integrantes; nenhum percentual de intervenção foi calculado |

Fonte: Elaborado pelos autores (2026).

A equipe informa manter registros de prompts e saídas. A existência, a disponibilidade e a integridade desse arquivo precisam ser confirmadas antes de afirmar rastreabilidade completa. A declaração também precisa ser assinada pelos integrantes. Percentuais sem método verificável não devem ser apresentados como indicadores auditados.

O modelo de Random Forest do produto não é IA generativa: foi treinado pela equipe com o script `scripts/treino_sisfall.py` sobre o dataset público SisFall.