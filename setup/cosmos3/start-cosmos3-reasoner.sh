#!/usr/bin/env bash
# Sobe o NVIDIA Cosmos3 Reasoner Edge FP8 (NIM) em http://localhost:8000 (API compatível com OpenAI).
# Pré-requisitos: chave NGC em NGC_API_KEY ou em ~/.ngc_api_key (chmod 600) e 'docker login nvcr.io' feito.
# Uso (dentro do WSL/Linux): bash setup/cosmos3/start-cosmos3-reasoner.sh
#
# Variáveis opcionais:
#   LOCAL_NIM_CACHE     cache dos pesos (padrão ~/nim-cache; no WSL, prefira o ext4 em vez de /mnt/d)
#   NIM_GPU_DEVICE      índice da GPU (padrão 0)
#   NIM_PROFILE_PATCH   caminho de um criteria.py local para montar sobre o do container. Usamos isso
#                       só em bancada, para rodar numa GPU fora da lista suportada (RTX 4090). O arquivo
#                       não é versionado. Veja setup/cosmos3/README.md.
set -euo pipefail

IMAGE="${NIM_IMAGE:-nvcr.io/nim/nvidia/cosmos3:2.1.0}"
NAME="${NIM_NAME:-cosmos3-reasoner}"
export LOCAL_NIM_CACHE="${LOCAL_NIM_CACHE:-$HOME/nim-cache}"
mkdir -p "$LOCAL_NIM_CACHE"

if [[ -z "${NGC_API_KEY:-}" ]]; then
  [[ -f "$HOME/.ngc_api_key" ]] || { echo "Defina NGC_API_KEY ou crie ~/.ngc_api_key"; exit 1; }
  NGC_API_KEY="$(<"$HOME/.ngc_api_key")"
fi
export NGC_API_KEY

EXTRA=()
if [[ -n "${NIM_PROFILE_PATCH:-}" ]]; then
  [[ -f "$NIM_PROFILE_PATCH" ]] || { echo "NIM_PROFILE_PATCH não encontrado: $NIM_PROFILE_PATCH"; exit 1; }
  echo "Aviso: montando $NIM_PROFILE_PATCH sobre a seleção de perfil do NIM (uso experimental)."
  EXTRA+=(-v "$(realpath "$NIM_PROFILE_PATCH"):/opt/nim/profile_selection/criteria.py:ro")
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
  --gpus "\"device=${NIM_GPU_DEVICE:-0}\"" --shm-size 16g \
  --ulimit memlock=-1 --ulimit stack=67108864 --ulimit nofile=65536:65536 \
  -p 8000:8000 -e NGC_API_KEY \
  -e NIM_MODEL_TYPE=reasoner -e NIM_MODEL_VARIANT=edge -e NIM_PRECISION=fp8 \
  -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" \
  "${EXTRA[@]}" \
  "$IMAGE"

echo "Container iniciado. Acompanhe com: docker logs -f $NAME"
echo "Espere ficar pronto com: bash setup/cosmos3/wait-ready.sh $NAME"
