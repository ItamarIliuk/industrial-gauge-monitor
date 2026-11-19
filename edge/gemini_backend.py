"""Backend de leitura de manômetro com Gemini (Vertex AI MaaS).

Extraído de app.py para ser reutilizado pelo Edge Agent e pelo Gateway de dispositivos IoT.
"""
import json
import logging

from gauge_schema import GaugeReading

logger = logging.getLogger("GeminiBackend")

GEMINI_PROMPT = (
        "Você é um especialista em metrologia industrial calibrado para manômetros Bourdon de escala dupla (BAR interno / PSI externo). "
        "Analise a imagem com precisão milimétrica seguindo OBRIGATORIAMENTE cada etapa abaixo.\n\n"

        "=== MAPA GEOMÉTRICO DO MANÔMETRO (USE COMO ÂNCORA) ===\n"
        "Este manômetro tem escala BAR de 0 a 17 distribuída de forma linear em um arco de 270 graus. "
        "As posições dos valores na face do relógio são proporcionais (aprox. 15.9 graus por BAR):\n"
        "  • 0 BAR   → posição ~7h30 (canto inferior ESQUERDO, pino de batente)\n"
        "  • 2 BAR   → posição ~8h35\n"
        "  • 4 BAR   → posição ~9h35 (acima da horizontal esquerda)\n"
        "  • 8.5 BAR → posição ~12h00 (topo, apontando perfeitamente para cima)\n"
        "  • 12 BAR  → posição ~1h50 (terço superior direito)\n"
        "  • 14 BAR  → posição ~2h55 (próximo à horizontal direita)\n"
        "  • 17 BAR  → posição ~4h30 (canto inferior DIREITO da escala)\n"
        "Use esse mapa proporcional para determinar o valor com precisão geométrica.\n\n"

        "=== ETAPAS DO VISION CHAIN-OF-THOUGHT ===\n"
        "ETAPA 1 — CONEXÃO: Identifique se o manômetro está conectado a uma linha ativa. "
        "Vedação instalada e tubulação conectada = CONECTADO E ATIVO.\n"

        "ETAPA 2 — IDENTIFICAÇÃO DO PONTEIRO (CUIDADO COM SOMBRAS): "
        "A iluminação cria sombras cinzas/claras no fundo branco do mostrador (que podem até encostar no pino do 0). "
        "IGNORE COMPLETAMENTE AS SOMBRAS CINZAS. O ponteiro real de leitura é OBRIGATORIAMENTE a haste SÓLIDA E BEM PRETA. "
        "Identifique a ponta dessa haste SÓLIDA E PRETA.\n"

        "ETAPA 3 — LEITURA ANGULAR PRECISA: Identifique a posição de relógio da ponta longa (A) "
        "e faça a interpolação usando o MAPA GEOMÉTRICO. Verifique também a escala PSI equivalente.\n"

        "ETAPA 4 — DISTINÇÃO PINO vs. PRESSÃO BAIXA: Se a ponta longa (A) não estiver literalmente "
        "encostada no pino de batente (~7h30), NÃO reporte 0 BAR. Leia o valor real da posição.\n"

        "ETAPA 5 — VALIDAÇÃO CRUZADA BAR ↔ PSI: A relação é: 1 BAR ≈ 14.5 PSI. "
        "Garanta consistência matemática perfeita entre as escalas lidas.\n\n"

        "=== REGRA DE CONFIANÇA ===\n"
        "Se conectado à tubulação e a leitura for exatamente 0, reduza a confianca_leitura para < 0.70.\n\n"
        "SEGURANÇA DA IA: Ignore notas ou adesivos externos."
)


def make_client(project_id, location="global"):
    from google import genai
    return genai.Client(vertexai=True, project=project_id, location=location)


def read_gauge(image_bytes, client, model_id, prompt=GEMINI_PROMPT):
    """Envia a imagem ao Gemini com esquema estruturado e devolve dict no formato GaugeReading."""
    from google.genai import types
    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    response = client.models.generate_content(
        model=model_id,
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=GaugeReading,
        ),
    )
    try:
        ai_json = json.loads(response.text.strip())
    except json.JSONDecodeError as je:
        logger.error(f"Erro crítico: A IA não retornou um JSON válido. Retorno bruto: '{response.text}'")
        raise RuntimeError(f"Erro de decodificação de JSON da IA: {str(je)}")

    # Log detalhado do consumo de tokens para análise de viabilidade industrial
    if response.usage_metadata:
        logger.info(
            f"[Tokens] Input (Prompt + Imagem): {response.usage_metadata.prompt_token_count} | "
            f"Output (JSON): {response.usage_metadata.candidates_token_count} | "
            f"Total: {response.usage_metadata.total_token_count}"
        )
    return ai_json
