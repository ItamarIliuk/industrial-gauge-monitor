#!/usr/bin/env bash
# Instala Docker Engine + NVIDIA Container Toolkit no Ubuntu 24.04 (WSL2)
# Uso (dentro do WSL):  bash setup/cosmos3/install-docker-wsl.sh
set -euo pipefail

echo "==> Pacotes base"
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

echo "==> Repositório oficial do Docker"
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

echo "==> Repositório do NVIDIA Container Toolkit"
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

echo "==> Instalando Docker + NVIDIA Container Toolkit"
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit

echo "==> Configurando runtime NVIDIA no Docker"
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl enable --now docker
sudo systemctl restart docker

echo "==> Adicionando $USER ao grupo docker (docker sem sudo)"
sudo usermod -aG docker "$USER"

echo "==> Teste de GPU no container"
sudo docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi

echo
echo "OK! Feche e reabra o terminal do Ubuntu (ou rode 'wsl --shutdown' no Windows) para o grupo docker valer."
