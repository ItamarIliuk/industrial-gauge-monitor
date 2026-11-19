# Validação ao vivo: Cosmos3 + câmera USB (07/11/2026)

**Setup:** câmera USB (1BCF:28C4, só entrega 640×480) capturando pelo Windows com DirectShow. NVIDIA Cosmos3 Edge Reasoner FP8 (NIM local, RTX 4090) localiza o mostrador, e a geometria mede a ponta fina da agulha. Manômetro STEELS de 0–16 bar / 0–250 psi, pressurizado por compressor. Referência: valor lido pelo operador no próprio manômetro.

## 1. Câmera longe, com a calibração das fotos de celular
O mostrador ocupava cerca de 150 px. Em 91 leituras a latência mediana foi de 0,62 s, sem nenhum alerta de visibilidade.
- 4 bar → 3,97 a 4,39 (média de ~4,25, +0,25). A leitura oscilava porque a resolução era baixa.
- ~8 bar → 7,31 a 7,55 (−0,5 a −0,7).
- O erro mudava de sinal ao longo da escala, então a calibração das fotos não servia para esta câmera.

## 2. Câmera aproximada e calibrada no local
Mostrador com cerca de 340 px, câmera de frente. Os pontos foram gravados com `bench/live_cosmos.py --calib-point <bar>`, usando a mediana de 10 leituras por patamar:

| Pressão | Ângulo da ponta fina | Dispersão |
|---|---|---|
| 0 bar (agulha no pino) | 228° | 4° |
| 2 bar | 252° | 1° |
| 4 bar | 281° | 1° |
| 8 bar | 347° | 3° |

`GAUGE_CALIB=228:0,252:2,281:4,347:8`

> O primeiro 0 foi gravado com a agulha encostada no pino de batente, cerca de 2° acima da marca impressa. Com a calibração 0/4/8, isso fazia o 2 bar ler 1,74. Por isso o 2 bar entrou como ponto de calibração.

## 3. Validação em patamares fora da calibração

| Patamar (operador) | Leitura (mediana de 5) | Faixa das 10 leituras | Erro |
|---|---|---|---|
| 6 bar | **5,94 bar · 86,2 psi** | 5,88 a 6,00 | −0,06 |
| 5 bar | **4,97 bar · 72,1 psi** | 4,91 a 5,15 | −0,03 |
| 3 bar | **3,17 bar · 46,0 psi** | 3,03 a 3,38 | +0,17* |

\* No recorte, a ponta está logo abaixo de 50 psi (3,45 bar), algo entre 3,2 e 3,3 pela leitura do mostrador. O erro real provavelmente é menor.

**Erro médio absoluto: cerca de 0,09 bar, ou 0,5% do fundo de escala de 16 bar.** A latência é de cerca de 0,55 s por leitura, com a imagem processada inteiramente na borda.

## Lições
1. **Calibrar na posição final da câmera.** A perspectiva muda a relação entre ângulo e pressão, e a escala vista pela câmera não é linear (13 a 16,5° por bar).
2. **Resolução do mostrador.** Passar de ~150 px para ~340 px reduziu a oscilação de ±0,2 para ±0,05 bar.
3. **Não use a agulha no pino como ponto de 0.** Calibre com pressões reais, por exemplo 2, 4 e 8 bar, e trate o pino só com a regra de zero (`GAUGE_ZERO_BAND`).
4. **A mediana móvel de 5 leituras** remove os saltos isolados de 2 a 3°.
5. **O Cosmos3 Edge sozinho** não lê o valor: ele segue o contrapeso. O papel dele é a percepção, ou seja, localizar o instrumento na cena.

## Reproduzir
```powershell
.\.venv\Scripts\python.exe bench\live_cosmos.py --calib-point 2   # repetir em cada patamar conhecido
.\.venv\Scripts\python.exe bench\live_cosmos.py --loop 1 --count 10 --keep
```
