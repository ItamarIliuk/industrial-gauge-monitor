# Industrial Gauge Monitor

Sistema IoT de visão na borda para manômetros industriais: Edge (câmera + Cosmos3/Gemini), Cloud (GCP),
UI (Streamlit), gateway IoT e firmware ESP32. Comandos em `README.md`.

## Máquinas
- Workstation (RTX 4090): Cosmos3 NIM local, benchmarks (`bench/`) e testes com câmera.
- Notebook (Dell G15, RTX 4050 de 6 GB): edição de código, UI, cloud e firmware.

## Sincronização entre máquinas
- No início da tarefa: `git pull --rebase`. Ao terminar: commit e push (perguntar antes do push).
- Planos ficam em `docs/plans/` (um arquivo por plano). Ver `docs/plans/README.md`.
- Nunca versionar `.env`, chaves de Service Account do GCP nem chaves do Gemini/NGC (o `.gitignore` já cobre).
- Imagens de bancada e capturas não entram no Git (só as que estão em `docs/`).
