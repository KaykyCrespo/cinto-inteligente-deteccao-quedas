# Relatorio de revisao academica do manual

Data: 12/11/2026.

## Escopo e documentos

Revisao autorizada apos o diagnostico inicial. Foram utilizados o manual integral, os apoios `Parte escrita atual.docx` e `Video e Manuais.docx`, o codigo do projeto e os relatorios de treinamento e RSSI. A estrutura de cinco secoes tecnicas exigida pelo apoio foi preservada.

Fonte editavel: [MANUAL_USUARIO_OPERACAO.md](MANUAL_USUARIO_OPERACAO.md).

Versoes finais verificadas:

- [Manual_Usuario_Operacao_Revisado.docx](Manual_Usuario_Operacao_Revisado.docx).
- [Manual_Usuario_Operacao_Revisado.pdf](Manual_Usuario_Operacao_Revisado.pdf).

O sufixo `_Revisado` foi utilizado porque a exportacao para o DOCX original encontrou bloqueio de gravacao. Os arquivos sem esse sufixo nao devem ser tratados como a revisao final verificada. O codigo do produto, os parametros do modelo, os dados brutos, os esquemas eletricos e a parte escrita de apoio nao foram modificados nesta revisao.

## Registro das alteracoes controladas

### 1. Arquitetura documental

**Original:** a parte escrita descreve MySQL, sensores por Advertising, 4 Hz, faixa de aceleracao de +/-2 g e calculo de BPM; o manual descreve SQLite, sensores por GATT, 100 Hz e +/-8 g.

**Revisado:** a Secao 1.1 identifica a implementacao documentada pelo manual e explicita que o firmware atual apresenta ECG bruto, sem calculo de frequencia cardiaca. As divergencias com a parte escrita foram registradas, sem reescrever o apoio.

**Justificativa:** impedir que a reproducao do prototipo seja baseada em uma arquitetura anterior. A conciliacao dos dois documentos permanece pendente de confirmacao da equipe.

### 2. Chave gangorra

**Original:** a chave aparece depois do MT3608 nas figuras e antes do conversor nas tabelas e instrucoes.

**Revisado:** aviso na Secao 2.3 exige confirmar a montagem fisica e alinhar as representacoes antes da reproducao por terceiros; explica que uma chave depois do MT3608 pode deixar o conversor alimentado.

**Justificativa:** nao escolher silenciosamente uma ligacao sem evidencia da montagem real. A divergencia nao foi corrigida nos desenhos.

### 3. Processamento local, notificacao e privacidade

**Original:** "sem nuvem [...] preserva a privacidade (LGPD)" e "recebe o aviso em segundos".

**Revisado:** distingue processamento local de notificacao por servico externo, condiciona Telegram a internet e configuracao e informa que nao ha medicao de latencia ponta a ponta apresentada no manual.

**Justificativa:** ausencia de cameras nao comprova conformidade legal; uma solicitacao de envio nao garante recebimento dentro de um prazo.

### 4. Hipotese orientadora

**Original:** associa alta sensibilidade e localizacao aproximada numa unica hipotese.

**Revisado:** preserva a hipotese, mas distingue a avaliacao do classificador no SisFall da validacao de localizacao e integracao. A hipotese integral nao e declarada comprovada pelas metricas de classificacao.

**Justificativa:** evitar extrapolar resultados por ensaio para eficacia clinica ou precisao espacial.

### 5. Dimensionamento energetico

**Original:** 350 mA tratados como pior caso; eficiencia de 85% e fracao util de 90% utilizadas para prever autonomia real maior.

**Revisado:** valores identificados como hipoteses, com necessidades de documentacao e medicao. Autonomias de 3,19 h e 1,62 h preservadas como estimativas condicionadas, nao tempos minimos garantidos.

**Justificativa:** preservar os calculos sem atribuir-lhes validacao experimental inexistente. O limite da chave interna do MT3608 foi diferenciado de corrente continua garantida na saida.

### 6. Recarga e temperatura

**Original:** recomendacao de manter antenas no carregador durante operacao; 5,5 h estimadas para recarga ligada; inferencia de corrente de pico a partir de aquecimento hipotetico.

**Revisado:** carga com dispositivo desligado e fora do corpo ate validar o gerenciamento de alimentacao. O exemplo de 5,5 h foi preservado como hipotese nao validada. Estimativas termicas passaram a exigir identificacao do regulador, especificacao compativel e medicao.

**Justificativa:** calculos simplificados nao demonstram termino correto de carga, protecao ou temperatura no case.

### 7. Calibracao RSSI

**Original:** calcular medianas e aplicar os parametros obtidos, sem criterio explicito de validacao.

**Revisado:** separar antena e origem, agregar por segundo, controlar geometria e orientacao, repetir as distancias e verificar residuos e erro de localizacao em dados separados. O relatorio de 1, 2, 3, 5 e 7 m e referido como exploratorio, sem nova calibracao sustentada.

**Justificativa:** RSSI nao monotono e condicoes desconhecidas impedem tratar o ajuste como referencia validada. O limite aceitavel de erro ainda deve ser definido pela equipe antes da avaliacao.

### 8. Atributos e escolha de modelo

**Original:** magnitudes dispensariam normalizacao; `post_std` indicaria imobilidade apos impacto; Random Forest teria inferencia em milissegundos e vantagens nao comparadas experimentalmente.

**Revisado:** distingue rotacao fixa ideal, offsets e escalonamento; define `tilt` pelo angulo entre vetores medios e `post_std` pela variabilidade no fim da janela. Explicita que `amin` nao comprova queda livre. A escolha do Random Forest foi fundamentada nas obras ja registradas no apoio, sem alegar superioridade experimental ou latencia nao medida.

**Justificativa:** descrever o calculo real e separar interpretacao fisica de evidencia. A comparacao com limiares permanece pendente.

### 9. Decisao e alertas

**Original:** passagem do limiar descrita como registro de queda e envio de mensagem.

**Revisado:** resultado descrito como evento de possivel queda; probabilidade nao tratada como risco clinico calibrado; notificacao condicionada a habilitacao, credenciais e conectividade.

**Justificativa:** evitar garantia operacional e interpretacao clinica nao demonstradas.

### 10. Declaracao de IA assistiva

**Original:** denominacoes de modelos, percentuais de 80% e 75%, arquivamento integral e assinatura apresentados sem comprovacao no manual.

**Revisado:** preserva as informacoes da equipe como declaradas e pendentes de conferencia, sem certificar versoes ou percentuais. Acrescenta o uso do GitHub Copilot na revisao deste manual, sem identificar um modelo nao confirmado. Rastreabilidade e assinatura requerem verificacao.

**Justificativa:** nao inventar versoes, registros ou metodos de quantificacao e nao eliminar silenciosamente informacoes declaradas pela equipe.

### 11. Citacoes e referencias

**Original:** obras citadas sem lista bibliografica no proprio manual.

**Revisado:** elemento pos-textual com Breiman, Giffinger, Gubbi, Pedregosa, Sucerquia e Zanella, recuperados do apoio, sem criar uma sexta secao tecnica. Referencias alinhadas a esquerda, com espacamento simples e destaque consistente dos titulos das obras.

**Justificativa:** permitir correspondencia entre citacoes e referencias. Os metadados ainda precisam ser conferidos contra fontes primarias; a presenca no apoio nao certifica sua exatidao.

### 12. Sumario, paginacao e hierarquia

**Original:** sumario sem subsecoes de terceiro nivel; capa aparentemente incluida na contagem; titulo "O que fazer ao receber um alerta" sem numero.

**Revisado:** sumario inclui subsecoes, contagem exclui a capa e a orientacao de atendimento foi identificada como 5.2.1. Criada a Secao 5.5 para pendencias antes da entrega.

**Justificativa:** manter correspondencia entre hierarquia, navegacao e paginacao sem alterar a estrutura institucional de cinco secoes.

### 13. Figuras, tabelas e quadros

**Original:** fontes das figuras herdavam 12 pt; 32 tabelas sem identificacao sequencial.

**Revisado:** 16 figuras com a frase de fonte aprovada em 10 pt e espacamento simples; imagem mantida com sua fonte. Conteudos identificados como 22 quadros descritivos e 10 tabelas quantitativas. O gerador diferencia bordas dos dois tipos de apresentacao.

**Justificativa:** melhorar rastreabilidade e padronizacao, sem modificar valores ou excluir figuras. A configuracao final deve ser confrontada com o manual institucional.

### 14. Escrita instrucional

**Original:** expressoes coloquiais e temperatura descrita como "morno" sem medicao.

**Revisado:** termos mais precisos e verificacoes explicitas, preservando instrucoes diretas adequadas a um manual. O exemplo de variaveis passou a identificar o arquivo de credenciais efetivamente fornecido.

**Justificativa:** formalidade nao deve substituir clareza nem converter observacoes nao medidas em fatos.

### 15. Projetos de impressao e registros audiovisuais

**Original:** os projetos eram referidos em `impressao_3d/` na raiz e os videos de `dados/testes/` nao tinham uma secao de rastreabilidade no manual.

**Revisado:** caminhos atualizados para `docs/impressao_3d/Case Cinto.3mf` e `docs/impressao_3d/Case Antena.3mf`, com links relativos. A Secao 5.6 e o Quadro 23 identificam os quatro videos disponiveis e os dados necessarios para associar cada registro a um ensaio. O README tambem foi atualizado.

**Justificativa:** videos podem complementar a evidencia visual dos procedimentos, mas seu nome ou existencia nao comprovam classificacao correta, latencia ou erro de localizacao. O conteudo e a correspondencia com CSVs, horarios e eventos ainda precisam ser conferidos. Os links MP4 foram preservados como arquivos externos no PDF; alguns leitores restringem sua abertura. O acesso no GitHub depende de publicacao e permissoes, nao verificadas nesta revisao.

## Validacao final

- Markdown integral processado na verificacao de estrutura e integridade.
- PDF final com 63 paginas; DOCX com 33 tabelas e 16 imagens.
- Cinco secoes tecnicas preservadas, com referencias como elemento pos-textual.
- Sequencias de 16 figuras, 23 quadros e 10 tabelas sem lacunas.
- Presenca das subsecoes 3.2.1, 3.3.4, 5.2.1, 5.5 e 5.6 no sumario verificada.
- Nove links relativos para pastas, projetos de impressao e videos conferidos contra caminhos locais existentes; quatro links MP4 e dois links 3MF preservados no DOCX.
- Inicio textual na pagina fisica 5, com numero exibido 4: a capa nao integra a contagem.
- Margens A4 verificadas: superior/esquerda de 3 cm e inferior/direita de 2 cm.
- Fontes das 16 figuras em 10 pt, espacamento simples e abaixo das imagens, na mesma pagina.
- Referencias com espacamento simples, alinhamento a esquerda e sem recuo de primeira linha.
- Valores de sensibilidade, precisao, F1, especificidade e acuracia preservados: 98,8%, 93,3%, 96,0%, 95,3% e 96,7%.
- Estimativas de autonomia preservadas e identificadas como condicionais.
- Nao houve retreinamento, recalibracao, alteracao de firmware ou commit nesta revisao.

## Pendencias antes da banca

Nao se declara conformidade integral com todas as normas ABNT vigentes sem obter e conferir o manual institucional aplicavel. A revisao melhora a apresentacao, mas nao substitui essa verificacao.

Ainda dependem da equipe: arquitetura final na parte escrita, posicao real da chave, protecao e comportamento de recarga, identificacao de reguladores, medicoes eletricas e de latencia, validacao de localizacao, comparacao com limiares, fontes bibliograficas primarias, registros de uso de IA e assinatura da declaracao. Esses itens nao devem ser apresentados como resolvidos apenas pela revisao do texto.