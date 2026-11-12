# PARTE ESCRITA DO TCC — INOVAÇÃO FRUGAL APLICADA À TECNOLOGIA ASSISTIVA

## Situação do documento

**Versão preparatória — levantamento inicial, evidências e planejamento. Data: 12/11/2026.**

O nome `PARTE_ESCRITA_FINAL` identifica o arquivo de trabalho solicitado, não uma versão científica concluída ou pronta para entrega. Não foi redigida a introdução, não foram reformulados objetivos ou hipóteses e não se iniciou a redação dos capítulos. O avanço para pesquisa bibliográfica, posicionamento e redação depende de aprovação, conforme o protocolo fornecido.

A inovação frugal constitui a perspectiva central desta investigação. A pergunta orientadora da concepção é identificar os recursos mínimos necessários para atender à necessidade essencial, sem comprometer segurança, qualidade ou adequação ao usuário. Isso é uma diretriz de investigação, não uma conclusão de que o protótipo já seja frugal, economicamente viável ou superior a alternativas comerciais.

O enquadramento institucional na vertente SmartCity pode ser mantido como contexto da aplicação. A inovação frugal deverá orientar as decisões de concepção, a comparação de arquiteturas, a análise econômica e a discussão dos resultados, sem ser reduzida à compra de componentes de menor preço.

**Referência econômica proposta:** um cinto e uma antena, sem AD8232, cabo de ECG ou eletrodos, com a infraestrutura necessária ao funcionamento da arquitetura atual. A configuração experimental ampliada será analisada separadamente.

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
| Fotografias e esquemas | `docs/esquemas/esquemas eletricos/`, `docs/IMAGENS/` | Registros de montagem, medição e diagramas | Posição da chave divergente entre figuras e tabelas; visor do multímetro não comprova todos os valores |
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

**Restrição assistiva:** a suficiência de um alerta local depende de haver um responsável em posição de acompanhá-lo. Se a finalidade essencial exigir notificação remota, Telegram ou mecanismo equivalente e conexão com a internet passam a integrar os requisitos e os custos mínimos desse cenário. Não retirar uma função necessária ao cuidado apenas para reduzir o orçamento.

## 5 Matriz de funcionalidades essenciais e complementares

As classificações abaixo são propostas para validação dos requisitos com a equipe e o orientador, não necessidades de usuários empiricamente comprovadas.

**Quadro 3 – Funcionalidade, essencialidade e configuração**

| Funcionalidade ou recurso | Classificação proposta | Referência mínima | Configuração ampliada | Evidência e decisão pendente |
|---|---|---|---|---|
| Aquisição inercial | Essencial à abordagem adotada | ESP32-C3 e MPU6050 | Mesmos componentes | Implementada; testar uso da referência mínima |
| Transporte dos sensores | Essencial | Uma antena GATT e MQTT | Uma antena GATT entre três unidades | Fluxo implementado; medir perdas, alcance e disponibilidade |
| Classificação de possível queda | Essencial | Random Forest no computador | Mesmo classificador | Métricas no SisFall; validação própria separada necessária |
| Alerta visual ao responsável | Essencial se acompanhamento local | Dashboard | Dashboard | Definir presença e resposta do operador |
| Notificação remota | Essencial quando o acompanhamento exigir distância | Incluir internet e serviço de alerta nesse cenário | Telegram implementado | Não considerar dispensável sem validar a necessidade assistiva |
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

A planilha [PARTE_ESCRITA_FINAL_CUSTOS.csv](PARTE_ESCRITA_FINAL_CUSTOS.csv) utiliza separador ponto e vírgula e contém 36 itens, com categoria, unidade, classificação, quantidade mínima proposta, quantidade ampliada da BOM, preço unitário, subtotais, fonte, data e observações. Os campos monetários estão em branco porque não foram encontrados comprovantes de preços nos arquivos textuais e apoios DOCX examinados. Campo vazio significa **não informado**, nunca custo nulo.

As quantidades da configuração ampliada são referências da BOM do manual, não auditoria física de estoque. Quantidades da configuração mínima são propostas. Itens cuja quantidade ainda não foi definida, como fios, fonte de recarga e proteção adicional, permanecem sem quantidade numérica. Confirmar composição de kits para não contar AD8232/cabo ou case/material/impressão duas vezes.

**Tabela 1 – Situação da estimativa econômica**

| Grandeza | Situação inicial | Dados necessários |
|---|---|---|
| Custo mínimo: um cinto e uma antena, sem ECG | Não calculável com preços comprovados disponíveis | Preços, quantidades confirmadas, montagem e infraestrutura |
| Custo ampliado: um cinto, três antenas e ECG | Não calculável | Mesma base de consulta e itens adicionais |
| Custo incremental das extensões | Não calculável | Diferença sob fronteira de custos equivalente |
| Custo de reprodução | Não calculável | Materiais, fabricação, configuração, frete, tributos e mão de obra |
| Custo de operação e manutenção | Não calculável | Energia, internet atribuível, reposição, suporte e horizonte temporal |
| Eventual preço comercial | Não estimado | Certificação, embalagem, garantia, suporte, escala e margem |

Fonte: Elaborado pelos autores (2026).

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

- Definir o conjunto essencial de funções com a finalidade assistiva: acompanhamento local ou remoto, disponibilidade e resposta esperadas.
- Realizar ensaio específico com um cinto e uma antena, sem ECG; separar viabilidade conceitual de operação validada.
- Confirmar posição real da chave e funcionamento da proteção, recarga e isolamento. A frugalidade não pode justificar redução de segurança.
- Confirmar preços reais, notas, fornecedores, datas, composição de kits e custos de reprodução.
- Medir energia do sistema completo, incluindo computador e roteador. Retirar dois nós não comprova a mesma redução percentual no consumo total.
- Medir latência, perdas e indisponibilidade. A versão atual do firmware não transmite contador de sequência; a quantificação de perdas exige cuidado metodológico.
- Associar vídeos a CSVs, horários, eventos e configuração; distinguir demonstração visual de avaliação quantitativa.
- Avaliar o classificador com dados próprios rotulados e comparar com limiares sob o mesmo protocolo. Não reutilizar as métricas do SisFall como validação de todo o protótipo mínimo.
- Confirmar o erro de localização na configuração ampliada. Os ensaios RSSI recentes não sustentam calibração confiável.
- Avaliar utilidade, conforto, manutenção e necessidade de capacitação do operador. Não afirmar adequação a idosos sem evidência pertinente.
- Conciliar parte escrita, manual e apresentação: MySQL/BPM/4 Hz/±2 g ainda aparecem no apoio antigo.
- Confirmar manual institucional, autorização para reorganizar a declaração de IA, registros de ferramentas e integridade das referências.

## 8 Relação das evidências com os três eixos da inovação frugal

**Quadro 5 – Eixos, indícios e critérios de verificação**

| Eixo | Indício inicial no projeto | O que ainda precisa ser demonstrado | Métricas propostas, sujeitas à aprovação |
|---|---|---|---|
| Redução de recursos | Referência com uma antena e sem módulo/eletrodos de ECG; processamento local existente | Custo e energia reduzidos sem perda essencial ou transferência oculta de custo | Quantidade de componentes, nós, custo de reprodução, potência média/pico e consumo por período |
| Simplicidade funcional | Separação entre detecção inercial e extensões de ECG/localização | Menor complexidade de montagem/operação e funções essenciais mantidas | Etapas e tempo de montagem/configuração, manutenção, erros operacionais e rastreabilidade |
| Acessibilidade e viabilidade | Componentes e projetos de case identificados; potencial de reprodução | Preços, disponibilidade, custo total, suporte e adequação ao responsável e usuário | Custo inicial e recorrente, disponibilidade local, necessidade de pessoal técnico e avaliação de uso |

Fonte: Elaborado pelos autores (2026), como proposta de operacionalização da investigação.

Redução de componentes é um indício mensurável, não definição suficiente de inovação frugal. A análise deverá mostrar quais benefícios essenciais permanecem, para quem são adequados e sob quais limites de segurança e desempenho. IA não é incompatível com frugalidade por ser sofisticada: sua inclusão precisa ser justificada por benefício proporcional a custo, infraestrutura e complexidade, com comparação pertinente.

## 9 Plano de pesquisa bibliográfica

Os materiais abaixo foram indicados pelo orientador no protocolo fornecido. **Não foram lidos nesta etapa**, e título, autores, método e resultados não foram presumidos a partir das URLs. A leitura bibliográfica será iniciada após aprovação do avanço.

**Quadro 6 – Materiais prioritários e situação de leitura**

| Identificador | Endereço indicado | Situação |
|---|---|---|
| B01 | <https://aging.jmir.org/2026/1/e88290> | Metadados e texto a consultar |
| B02 | <https://www.mdpi.com/1424-8220/21/18/6051> | Metadados e texto a consultar |
| B03 | <https://www.mdpi.com/2079-9292/15/16/3669> | Metadados e texto a consultar |
| B04 | <https://www.sciencedirect.com/science/article/abs/pii/S1383762126001141> | Conferir acesso; não equiparar resumo à leitura integral |
| B05 | <https://pmc.ncbi.nlm.nih.gov/articles/PMC11397814/> | Metadados e texto a consultar |
| B06 | <https://repositorio.ifmg.edu.br/items/a8c31f0a-d1c3-4f66-8d62-45a40199959a> | Documento, autoria e instituição a consultar |

Fonte: Endereços fornecidos pelo orientador, reproduzidos no protocolo de trabalho apresentado pela equipe.

O fichamento de cada publicação deverá registrar título, autores, ano, veículo, DOI quando disponível, acesso integral ou parcial, objetivo, metodologia, amostra, resultados, limitações e contribuição específica para esta pesquisa. Não pressupor que todos os materiais tratem diretamente de inovação frugal.

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

**Apêndice B — Declaração de utilização de inteligência artificial:** reservar para a declaração independente, após confirmar ferramentas, versões, registros, percentuais e assinatura. A declaração ainda não foi extraída ou retirada do manual nesta etapa.

**Conflito de requisitos a deliberar:** o apoio institucional de vídeo/manual exige declaração de IA na Seção 4 do manual, enquanto o novo protocolo propõe retirá-la para o Apêndice B. Confirmar com o orientador se o manual do Apêndice A deve manter uma remissão à declaração independente e se a versão entregue separadamente precisa conservar a declaração completa. Não alterar silenciosamente a exigência institucional ou excluir informações agora.

Materiais de autoria da equipe poderão ser apêndices adicionais; documentos de terceiros, quando pertinentes e autorizados, serão anexos. Utilizar **REFERÊNCIAS** para obras efetivamente citadas, sem inventar fontes. As obras indicadas em planejamento de busca não são referências automaticamente utilizadas no texto científico.

A conformidade integral com ABNT NBR 14724, 10520, 6023, 6024, 6027 e 6028 e com exigências específicas da UNIP depende da consulta às versões aplicáveis e ao manual institucional. Esta versão preparatória não constitui certificação de conformidade ou monografia normalizada para entrega.

## 12 Deliberações para avançar

1. Aprovar o uso do documento como base preparatória e a separação entre referência mínima e configuração ampliada.
2. Definir se o alerta remoto integra a necessidade essencial e quais limites de falha, atraso e resposta são aceitáveis.
3. Confirmar a BOM mínima e os procedimentos necessários ao modo sem ECG, sem executar alterações de firmware nesta etapa.
4. Fornecer comprovantes de compras/cotações e autorizar a consulta de preços de soluções comparáveis.
5. Aprovar o plano bibliográfico e o fichamento dos seis materiais indicados.
6. Validar problema, objetivos, hipóteses e critérios de inovação frugal somente depois dessas evidências, antes de redigir capítulos.
7. Confirmar o manual institucional e resolver a localização da declaração de IA entre manual e Apêndice B.

Nenhuma conclusão sobre viabilidade econômica, eficácia clínica, localização com uma antena ou validação integral da configuração mínima foi estabelecida neste levantamento. O próximo avanço depende de aprovação da equipe, conforme o protocolo.