#!/usr/bin/env bash
# Espera o NIM ficar pronto (ou o container sair) e mostra os últimos logs.
NAME="${1:-cosmos3-reasoner}"
for i in $(seq 1 180); do
  s=$(docker inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null)
  if [ "$s" != "running" ]; then echo "EXITED: $s"; break; fi
  if curl -sf localhost:8000/v1/health/ready >/dev/null; then echo "READY after $((i*10))s"; break; fi
  sleep 10
done
docker logs --tail 30 "$NAME" 2>&1
