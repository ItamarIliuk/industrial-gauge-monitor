import os
import sys
import pandas as pd
from google.cloud import bigquery

# Garante suporte a UTF-8 no console Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "seu-projeto-gcp")
    dataset_id = os.getenv("BQ_DATASET", "telemetry_db")
    table_id = os.getenv("BQ_TABLE", "manometer_readings")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    print("==========================================================================")
    print(f"  Consulta BigQuery - Histórico de Leituras Industrial Gauge")
    print(f"  Projeto: {project_id} | Tabela: {dataset_id}.{table_id}")
    print("==========================================================================")

    try:
        client = bigquery.Client(project=project_id)
        query = f"""
            SELECT 
                timestamp,
                device_id,
                pressao_bar,
                pressao_psi,
                confianca
            FROM `{project_id}.{dataset_id}.{table_id}`
            ORDER BY timestamp DESC
            LIMIT {limit}
        """
        print(f">> Executando Query SQL no GCP BigQuery...")
        query_job = client.query(query)
        df = query_job.to_dataframe()

        if df.empty:
            print("\n[AVISO] A tabela está vazia ou não contém registros no momento.")
        else:
            print(f"\n[OK] Total de {len(df)} registros encontrados:\n")
            print(df.to_string(index=False))
            print("\nEstatísticas:")
            print(f" - Pressão Média: {df['pressao_bar'].mean():.2f} BAR")
            print(f" - Pressão Máxima: {df['pressao_bar'].max():.2f} BAR")
            print(f" - Média de Confiança IA: {df['confianca'].mean():.1%}")

    except Exception as e:
        print(f"\n[ERRO] Falha ao acessar BigQuery: {str(e)}")
        print("\nExibindo dados de demonstração simulados:")
        from datetime import datetime, timedelta
        now = datetime.now()
        data = {
            "timestamp": [now - timedelta(minutes=i*5) for i in range(5)],
            "device_id": ["manometro-caldeira-01"] * 5,
            "pressao_bar": [7.8, 7.5, 7.9, 8.1, 7.7],
            "pressao_psi": [113.1, 108.8, 114.6, 117.5, 111.7],
            "confianca": [0.98, 0.96, 0.99, 0.97, 0.95]
        }
        df_sim = pd.DataFrame(data)
        print(df_sim.to_string(index=False))

if __name__ == "__main__":
    main()

