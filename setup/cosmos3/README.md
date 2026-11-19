# Setup do NVIDIA Cosmos3 (NIM local)

Scripts para subir o **Cosmos3 Edge Reasoner FP8** (`nvcr.io/nim/nvidia/cosmos3:2.1.0`) numa máquina com GPU
NVIDIA e usá-lo como backend do Edge Agent e do gateway (`GAUGE_BACKEND=cosmos`).
Testado em Windows 11 + WSL2 Ubuntu 24.04 + Docker, com uma RTX 4090 de 24 GB. O modelo usa cerca de 19 GB de VRAM.

## Passo a passo (dentro do Ubuntu/WSL, na raiz do repositório)

1. **Docker + NVIDIA Container Toolkit**. O script termina rodando `nvidia-smi` num container para conferir a GPU:
   ```bash
   bash setup/cosmos3/install-docker-wsl.sh
   ```
   Depois, feche e reabra o terminal para o grupo `docker` passar a valer.

2. **Credenciais do NGC**. Use a chave da sua conta em <https://ngc.nvidia.com>. Ela não é versionada:
   ```bash
   install -m 600 /dev/null ~/.ngc_api_key && nano ~/.ngc_api_key    # cole a chave
   docker login nvcr.io -u '$oauthtoken' --password-stdin < ~/.ngc_api_key
   ```

3. **Subir o NIM e esperar ficar pronto**. Na primeira vez são cerca de 8 minutos, incluindo o download dos pesos:
   ```bash
   bash setup/cosmos3/start-cosmos3-reasoner.sh
   bash setup/cosmos3/wait-ready.sh
   curl -s localhost:8000/v1/health/ready
   ```

4. **Usar no projeto**. No Windows, use `127.0.0.1` em vez de `localhost`, para evitar ~2 s de tentativa por IPv6:
   ```bash
   GAUGE_BACKEND=cosmos COSMOS_URL=http://127.0.0.1:8000 python edge/app.py
   python bench/compare.py <pasta_de_fotos> --backends cosmos
   ```

## Observações

- **GPU suportada.** O NIM escolhe o perfil conforme a GPU. Na versão 2.1.0, a RTX 4090 não está na lista do
  perfil Reasoner. Para os experimentos de bancada, montamos um `criteria.py` local sem essa restrição, com a
  variável `NIM_PROFILE_PATCH`. Esse arquivo não é distribuído neste repositório. Em produção, o alvo é uma
  plataforma suportada oficialmente, como Jetson ou GPU de data center.
- **WSL desligando o NIM.** O WSL 3.x encerra a distro, e o container junto, quando o último terminal `wsl.exe`
  fecha. Deixe um terminal aberto com:
  ```powershell
  wsl -d Ubuntu-24.04 -- bash -lc "docker start cosmos3-reasoner; exec sleep infinity"
  ```
  Outra opção é ajustar o tempo de ociosidade da VM no `.wslconfig` do Windows.
