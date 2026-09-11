# Estudo de Viabilidade Técnico-Econômica: Monitoramento de Manômetros por Visão Computacional (Gemini API)

Este documento apresenta uma análise aprofundada de custos, consumo de tokens, impactos metrológicos e Retorno sobre Investimento (ROI) para a implementação do monitoramento automático de manômetros analógicos industriais através da API do Gemini, utilizando o modelo **Gemini 3.6 Flash**.

---

## 1. Contexto Metrológico e Validação de Hipótese

### A Hipótese da Calibração é Verdadeira?
> [!IMPORTANT]
> **SIM, a hipótese é 100% VERDADEIRA e mandatória por normas regulamentadoras.**
> A câmera e a IA do Gemini realizam a **leitura ótica da indicação mecânica** (posição angular do ponteiro na escala graduada). O sistema digitaliza o dado visual, mas o transdutor primário da grandeza física continua sendo o mecanismo elástico do manômetro (tubo de Bourdon, fole ou diafragma).

### Implicações Metrológicas e Normativas (NR-13 e ISO/IEC 17025)
1. **Permanência do Custo de Calibração:** Se o manômetro analógico subjacente sofrer histerese mecânica, deformação plástica por pulsação ou perda de calibração, a IA lerá com exatidão milimétrica uma indicação fisicamente errada (*"Garbage In, Garbage Out"*). Logo, a calibração periódica por laboratório acreditado (RBC/INMETRO) é obrigatória tanto no sistema legado quanto no retrofit.
2. **Periodicidade:** Conforme a criticidade do processo e exigências da NR-13 (Caldeiras, Vasos de Pressão e Tubulações), os manômetros devem ser calibrados em intervalos de 6 a 12 meses.
3. **Custo Médio de Mercado:** R$ 150,00 a R$ 250,00 por instrumento para calibração padrão RBC, além dos custos logísticos ou de desmontagem temporária.

---

## 2. Arquitetura da Solução e Retrofit Não-Invasivo

A solução proposta preserva a instrumentação existente, evitando furações em linhas pressurizadas:
1. **Dispositivo de Borda (Edge):** Câmera industrial com anel de iluminação LED e microcomputador local (ex: Raspberry Pi 4/5 ou Mini-PC industrial).
2. **Processamento Cognitivo:** API do **Gemini 3.6 Flash** interpretando a imagem do mostrador, realizando leitura angular, validação de limites operacionais e verificação de integridade visual.
3. **Pipeline Cloud SCADA:** Publicação via Pub/Sub para persistência em Firestore (UI em tempo real) e BigQuery (série temporal e manutenção preditiva).

---

## 3. Composição de Tokens e Custos de IA (Gemini 3.6 Flash)

O modelo **`gemini-3.6-flash`** apresenta precificação altamente competitiva ($0,15/1M tokens de entrada e $0,60/1M tokens de saída).

### Consumo por Leitura
| Componente | Descrição | Tokens Médios |
| :--- | :--- | :--- |
| **Input (Imagem ROI)** | Crop otimizado da região do mostrador em patches estruturados | **258 tokens** |
| **Input (Prompt + Schema)** | Prompt de calibração visual + Schema Pydantic | **242 tokens** |
| **Output (JSON Estruturado)** | Pressão (BAR/PSI), status, nível de confiança e anomalias | **~150 tokens** |
| **Total por Ciclo** | **Soma Entrada + Saída** | **~650 tokens** |

### Projeção Financeira de Nuvem por Sensor (Câmbio USD = R$ 5,00)

| Cenário de Amostragem | Leituras/Mês | Tokens Input/mês | Tokens Output/mês | Custo IA/mês (USD) | Custo IA/mês (BRL) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cenário A: 5 min** (Supervisão Padrão) | 8.640 | 4.320.000 | 1.296.000 | **$1,43** | **R$ 7,13** |
| **Cenário B: 1 min** (Linha Crítica) | 43.200 | 21.600.000 | 6.480.000 | **$7,13** | **R$ 35,64** |
| **Cenário C: Edge Trigger** (Leitura apenas em delta/mudança) | ~2.500 | 1.250.000 | 375.000 | **$0,41** | **R$ 2,06** |

---

## 4. Comparativo Triplo de Viabilidade Econômica (10 Instrumentos / 1 Ano)

Para um estudo de viabilidade rigoroso, comparamos três abordagens reais do parque industrial:
1. **Opção 1: Legado Puro (Ronda Humana):** Manômetros existentes lidos manualmente por operadores de campo com prancheta/tablet.
2. **Opção 2: Automação Convencional (Transmissores 4-20mA / HART):** Troca completa por transmissores de pressão eletrônicos industriais cabeados até o CLP.
3. **Opção 3: Retrofit IA Gemini 3.6 Flash (Câmera IoT):** Digitalização não-invasiva dos manômetros mecânicos existentes com IA.

### Tabela de Custos Comparativa (Base: 10 Pontos de Medição em 12 meses)

| Item de Custo | Opção 1: Legado Puro (Ronda Humana) | Opção 2: Transmissores 4-20mA / CLP | Opção 3: Retrofit IA Gemini (5 min) |
| :--- | :--- | :--- | :--- |
| **CAPEX Inicial (Hardware)** | **R$ 0** (Instrumentos já instalados) | **R$ 45.000** (10 transmissores industriais de pressão) | **R$ 4.000** (10 Câmeras industriais + 2 Hubs Edge) |
| **CAPEX Infra / Instalação** | **R$ 0** | **R$ 25.000** (Parada de planta, solda/flanges, passamento de eletrocalhas e cartões CLP) | **R$ 2.000** (Fixação de suportes magnéticos e rede Wi-Fi/Ethernet) |
| **Custo de Calibração Periódica (OPEX)** | **R$ 2.000/ano** (10 manômetros a R$ 200/unid) | **R$ 4.000/ano** (Calibração de transmissores de pressão + malha 4-20mA a R$ 400/unid) | **R$ 2.000/ano** (10 manômetros a R$ 200/unid - custo idêntico ao legado) |
| **Custo Operacional Direto (OPEX)** | **R$ 28.800/ano** (1 operador dedicando 1h/dia em rondas = R$ 2.400/mês mão de obra) | **R$ 1.200/ano** (Manutenção preventiva de cabeamento e bornes) | **R$ 855,60/ano** (Consumo da API Gemini 3.6 Flash no Cenário A) |
| **Manutenção Periféricos / Limpeza (OPEX)** | **R$ 0** | **R$ 500/ano** | **R$ 500/ano** (Limpeza periódica de lentes das câmeras) |
| **Custo Total no 1º Ano (CAPEX + OPEX)** | **R$ 30.800** | **R$ 75.700** | **R$ 9.355,60** |
| **Custo Recorrente Anual (Anos seguintes)** | **R$ 30.800/ano** | **R$ 5.700/ano** | **R$ 3.355,60/ano** |

---

## 5. Análise de Retorno sobre Investimento (ROI) e Payback

### A. Retrofit IA vs. Automação Convencional (4-20mA)
* **Economia no 1º Ano:** $R\$ 75.700 - R\$ 9.355,60 = \mathbf{R\$ 66.344,40}$ de economia imediata (redução de 87,6% no desembolso total).
* **Vantagem de Implantação:** O retrofit é executado sem necessidade de despressurizar linhas, drenar fluídos ou parar a caldeira/produção.

### B. Retrofit IA vs. Legado (Ronda Humana)
* **Economia Operacional Anual:** $R\$ 30.800 - R\$ 3.355,60 = \mathbf{R\$ 27.444,40/ano}$ em horas-homem liberadas para atividades preventivas nobres.
* **Investimento Inicial Retrofit (CAPEX):** R$ 6.000,00.
* **Tempo de Payback:** $\frac{R\$ 6.000,00}{R\$ 27.444,40} \times 12 \text{ meses} \approx \mathbf{2,6 \text{ meses}}$.

---

## 6. Ganhos Adicionais da IA na Gestão Metrológica e Calibração

Longe de ser apenas um leitor passivo, a introdução da visão computacional com Gemini agrega recursos que o manômetro legado não possuía:

1. **Detecção Precoce de Falha do Elemento Elástico (Zero-Drift):**
   * Em manômetros analógicos, o tubo de Bourdon perde elasticidade com o tempo, acumulando desvio de zero. O modelo de IA pode detectar se, durante paradas de linha conhecidas, o ponteiro não retorna exatamente à marcação `0 BAR`, sinalizando necessidade de calibração imediata antes do prazo de 12 meses.
2. **Identificação de Ponteiro Travado (Mecânica Danificada):**
   * Se a pressão do sistema varia (conforme outros sensores da linha ou ciclos da bomba), mas o ponteiro do manômetro permanece perfeitamente estático por múltiplas leituras, a IA emite um alerta de suspeita de travamento por sujeira ou golpe de aríete.
3. **Rastreabilidade e Log Fotográfico para Auditorias:**
   * Para fins de auditoria de qualidade (ISO 9001, ANVISA, IATF), cada leitura é acompanhada pelo recorte fotográfico com carimbo de data/hora, eliminando erros de transcrição manual ou anotações forjadas em pranchetas.
4. **Gestão de Selo de Calibração (OCR de Etiqueta):**
   * A câmera pode ser configurada para inspecionar periodicamente a etiqueta de calibração colada no visor do manômetro, alertando automaticamente o setor de manutenção sobre a proximidade do vencimento da calibração RBC.

---

## 7. Conclusão

A hipótese de que a **calibração periódica é um custo inerente mantido no projeto de retrofit é rigorosamente confirmada**. A visão computacional não elimina o componente mecânico de medição, mas sim a necessidade da presença humana para sua supervisão.

Ao computar os custos reais de calibração metrológica (R$ 200/ano por ponto), o projeto de retrofit com **Gemini 3.6 Flash** permanece amplamente viável, entregando:
* **Payback em menos de 3 meses** em relação à ronda manual.
* **Economia superior a R$ 66.000,00** no primeiro ano frente à substituição por transmissores 4-20mA.
* **Aumento da confiabilidade metrológica**, adicionando vigilância 24/7 contra travamento mecânico e desvios de calibração.
