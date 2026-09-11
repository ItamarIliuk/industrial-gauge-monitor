# Estudo de Viabilidade Econômica: Monitoramento de Manômetros por Visão Computacional (Gemini API)

Este documento apresenta a análise de custos, consumo de tokens e o Retorno sobre Investimento (ROI) para a implementação do monitoramento automático de manômetros analógicos industriais através da API do Gemini, atualizado após a integração e migração para o modelo **Gemini 3.6 Flash**.

---

## 1. Arquitetura da Solução IoT

A solução adota uma abordagem de **Retrofit Não-Invasivo**, composta por:
1. **Dispositivo de Borda (Edge):** Câmera industrial de baixo custo acoplada a um microcomputador (ex: Raspberry Pi ou Mini-PC).
2. **Processamento Cognitivo:** API do **Gemini 3.6 Flash** interpretando a imagem do ponteiro via visão computacional com validação estrita por esquema estruturado (Pydantic).
3. **Pipeline em Nuvem:** Envio seguro via GCP Pub/Sub para persistência em tempo real no Firestore (Dashboard SCADA) e BigQuery (Banco de Dados de Telemetria).

---

## 2. Composição e Consumo de Tokens (Por Leitura)

O modelo utilizado é o **`gemini-3.6-flash`**, que garante altíssima velocidade, raciocínio visual apurado para metrologia e suporte nativo a respostas estruturadas JSON via Pydantic. Cada ciclo de leitura consome tokens divididos em três frentes:

| Tipo de Consumo | Descrição | Volume Médio de Tokens |
| :--- | :--- | :--- |
| **Input (Imagem)** | Divisão do crop da imagem em patches visuais estruturados. | **258 tokens** (tamanho padrão para ROI recortado) |
| **Input (Prompt + Schema)** | Prompt de análise focado em Vision Chain-of-Thought e parâmetros Pydantic. | **242 tokens** (otimizado via esquema estruturado) |
| **Output (JSON)** | Resposta estruturada limpa (pressão BAR/PSI, confiança e alertas). | **~150 tokens** |
| **Total por Leitura** | **Soma dos insumos de entrada e saída.** | **~650 tokens** (500 Input / 150 Output) |

> [!NOTE]
> O Agente de Borda registra esse consumo em tempo real nos logs locais através da tag `[Tokens]`.

---

## 3. Projeção Mensal de Custos Financeiros (Gemini 3.6 Flash)

A precificação estipulada para o modelo **Gemini 3.6 Flash** (MaaS via Google GenAI / Vertex AI) é altamente otimizada para alta escala:
* **Custo de Entrada (Input):** $0,15 USD / 1M tokens ($0,00015 por 1.000 tokens - incluindo multimodal/imagens)
* **Custo de Saída (Output):** $0,60 USD / 1M tokens ($0,00060 por 1.000 tokens)

Abaixo, simulamos dois cenários reais de operação industrial para 1 (um) dispositivo ativo 24h por dia durante 30 dias (assumindo o câmbio médio de R$ 5,00/USD):

### Cenário A: Amostragem a cada 5 Minutos (Padrão de Supervisão)
* **Leituras por hora:** 12
* **Leituras por dia:** 288
* **Leituras por mês:** 8.640 leituras

* **Tokens de Entrada/Mês:** $8.640 \times 500 = 4.320.000$ tokens ($0,648 USD)
* **Tokens de Saída/Mês:** $8.640 \times 150 = 1.296.000$ tokens ($0,778 USD)
* **Custo Total por Sensor:** **$1,43 USD / mês** (Aproximadamente **R$ 7,13 / mês** por manômetro).

---

### Cenário B: Amostragem a cada 1 Minuto (Alta Frequência / Crítico)
* **Leituras por hora:** 60
* **Leituras por dia:** 1.440
* **Leituras por mês:** 43.200 leituras

* **Tokens de Entrada/Mês:** $43.200 \times 500 = 21.600.000$ tokens ($3,24 USD)
* **Tokens de Saída/Mês:** $43.200 \times 150 = 6.480.000$ tokens ($3,89 USD)
* **Custo Total por Sensor:** **$7,13 USD / mês** (Aproximadamente **R$ 35,64 / mês** por manômetro).

---

## 4. Comparativo de ROI Atualizado (10 Sensores na Planta)

A adoção do **Gemini 3.6 Flash** resulta em um custo operacional (OPEX) extremamente baixo. Comparamos abaixo a viabilidade para a instalação de **10 sensores** na planta por um período de 12 meses:

| Critério de Comparação | Sensor Físico de Pressão (Transmissor 4-20mA / SCADA) | Câmera IoT + IA Gemini 3.6 Flash (Cenário A - 5 min) |
| :--- | :--- | :--- |
| **Instalação / Instabilidade** | **Intrusivo:** Requer perfuração da tubulação, parada da caldeira/vapor e solda. | **Não-Intrusivo:** Fixação externa por suporte magnético sobre o manômetro existente. |
| **Custo de Hardware (CAPEX)** | R$ 35.000 a R$ 60.000 (10 transmissores + Módulos de Comunicação). | R$ 3.000 a R$ 5.000 (10 Câmeras USB + Microcomputadores leves). |
| **Mão de Obra e Infraestrutura** | R$ 20.000 (Passagem de cabos de sinal/alimentação e calibração inicial). | R$ 2.000 (Configuração de rede e fixação). |
| **Custo Recorrente Anual (OPEX)** | R$ 5.000/ano (calibração periódica obrigatória a cada 12 meses). | **~R$ 855,60/ano** (consumo de API Gemini no Cenário de 5 min: R$ 71,30/mês para os 10 sensores). |
| **Custo Total Acumulado (1º Ano)** | **R$ 60.000 a R$ 85.000** | **R$ 5.855,60 a R$ 7.855,60** |
| **Tempo de Payback** | **18 a 24 meses** | **< 2 meses** |

> [!TIP]
> Com a eficiência de custo do **Gemini 3.6 Flash**, a solução de Visão Computacional gera uma economia superior a **R$ 54.000 no primeiro ano** para 10 sensores, com um tempo de Payback inferior a 2 meses.

---

## 5. Estratégias de Otimização de Custos (OPEX)

Para plantas com dezenas de manômetros ou que exijam amostragem de alta frequência, recomendamos as seguintes técnicas:
1. **Gatilhos de Eventos (Event-driven sampling):** Reduzir a frequência de leitura quando o sistema está em repouso e aumentá-la para 1 minuto apenas quando variações físicas rápidas de pressão forem detectadas ou quando a planta estiver em operação ativa.
2. **Filtragem Local por Borda (Edge Delta Filtering):** O microcomputador local pode comparar os frames consecutivos e enviar para a API do Gemini somente se houver mudança de pixels indicando que o ponteiro se moveu. Se o ponteiro estiver estático, o agente local publica a leitura anterior economizando tokens.
