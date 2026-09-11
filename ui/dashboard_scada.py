import os
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from google.cloud import firestore, bigquery
import time
import pytz
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# Configuração de Fuso Horário Local
BR_TIMEZONE = pytz.timezone('America/Sao_Paulo')

# Configuração da Página para Estilo Industrial (Dark Mode por padrão no Streamlit)
st.set_page_config(
    page_title="SCADA - Monitoramento de Caldeira",
    page_icon="🏗️",
    layout="wide"
)

# Estilização CSS para simular interface de supervisório
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    .stMetric {
        background-color: #1f2937;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #3b82f6;
    }
    </style>
    """, unsafe_allow_html=True)

# Inicialização dos Clientes GCP com Fallback Defensivo
@st.cache_resource
def get_db_client():
    try:
        return firestore.Client()
    except Exception:
        return None

@st.cache_resource
def get_bq_client():
    try:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "seu-projeto-gcp")
        return bigquery.Client(project=project_id)
    except Exception:
        return None

def fetch_gauge_data():
    """Busca dados em tempo real do Firestore com tratamento de erro."""
    try:
        db = get_db_client()
        if db is None:
            return None
        doc_ref = db.collection("realtime_gauges").document("manometro-caldeira-01")
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        st.sidebar.warning(f"Aviso Firestore: Conexão indisponível ({str(e)}).")
    return None

def fetch_bigquery_history(limit=50):
    """Busca o histórico de leituras armazenadas no BigQuery."""
    try:
        bq = get_bq_client()
        if bq is None:
            return None
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "seu-projeto-gcp")
        dataset_id = os.getenv("BQ_DATASET", "telemetry_db")
        table_id = os.getenv("BQ_TABLE", "manometer_readings")
        
        query = f"""
            SELECT timestamp, device_id, pressao_bar, pressao_psi, confianca
            FROM `{project_id}.{dataset_id}.{table_id}`
            ORDER BY timestamp DESC
            LIMIT {limit}
        """
        df = bq.query(query).to_dataframe()
        return df
    except Exception as e:
        st.sidebar.warning(f"Aviso BigQuery: Consulta indisponível ({str(e)}).")
        return None

def get_simulated_history():
    """Gera histórico simulado realista para o BigQuery em modo demonstração."""
    now = datetime.now(BR_TIMEZONE)
    timestamps = [now - timedelta(minutes=i * 5) for i in range(20)]
    data = {
        "timestamp": timestamps,
        "device_id": ["manometro-caldeira-01"] * 20,
        "pressao_bar": [7.8, 7.5, 7.9, 8.1, 7.7, 7.6, 8.2, 8.0, 7.4, 7.8, 7.9, 7.6, 7.7, 8.1, 7.8, 7.5, 7.9, 8.0, 7.7, 7.6],
        "pressao_psi": [113.1, 108.8, 114.6, 117.5, 111.7, 110.2, 118.9, 116.0, 107.3, 113.1, 114.6, 110.2, 111.7, 117.5, 113.1, 108.8, 114.6, 116.0, 111.7, 110.2],
        "confianca": [0.98, 0.96, 0.99, 0.97, 0.95, 0.98, 0.99, 0.96, 0.94, 0.97, 0.98, 0.99, 0.97, 0.96, 0.98, 0.97, 0.99, 0.98, 0.96, 0.97]
    }
    return pd.DataFrame(data)

def create_gauge_chart(value):
    """Renderiza o manômetro digital usando Plotly."""
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': "Pressão Realtime (BAR)", 'font': {'size': 22}},
        gauge = {
            'axis': {'range': [0, 17], 'tickwidth': 1, 'tickcolor': "white"},
            'bar': {'color': "#1f2937"},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 10], 'color': "#10b981"},    # Verde (Operação Normal)
                {'range': [10, 14], 'color': "#f59e0b"},   # Amarelo (Atenção)
                {'range': [14, 17], 'color': "#ef4444"}    # Vermelho (Crítico)
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 14
            }
        }
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font={'color': "white", 'family': "Arial"},
        margin=dict(l=20, r=20, t=50, b=20),
        height=380
    )
    return fig

# --- UI PRINCIPAL ---

st.sidebar.title("⚙️ Painel de Controle SCADA")
demo_mode = st.sidebar.checkbox("Modo Demonstração (Dados Simulados)", value=False)

st.title("🏗️ Sistema de Supervisão de Caldeiras - Planta 01")
st.subheader("Dispositivo: manometro-caldeira-01 | BigQuery Analytics Active")

data = None
if not demo_mode:
    data = fetch_gauge_data()

if demo_mode or data is None:
    if not demo_mode and data is None:
        st.sidebar.info("Modo Demonstração ativado automaticamente por falta de conexão com Firestore.")
    data = {
        "last_reading": {"bar": 7.8, "psi": 113.1, "confianca": 0.98},
        "status": "NORMAL",
        "updated_at": datetime.now(pytz.UTC)
    }

if data:
    reading = data.get("last_reading", {})
    bar_val = reading.get("bar", 0.0)
    psi_val = reading.get("psi", 0.0)
    confianca = reading.get("confianca", 0.0)
    status = data.get("status", "NORMAL")
    
    updated_at_utc = data.get("updated_at")
    try:
        updated_at_br = updated_at_utc.astimezone(BR_TIMEZONE) if updated_at_utc and hasattr(updated_at_utc, 'astimezone') else datetime.now(BR_TIMEZONE)
    except Exception:
        updated_at_br = datetime.now(BR_TIMEZONE)

    # Callouts de Alerta e Segurança na UI
    if status == "LOW_CONFIDENCE":
        st.error("🚨 LEITURA NÃO CONFIÁVEL: A IA não pôde ler o manômetro com precisão suficiente. Exibindo último valor válido conhecido. Verifique o equipamento fisicamente!")
    elif status == "RANGE_ERROR":
        st.error("🚨 LEITURA ANÔMALA REJEITADA: O valor lido mais recente está fora dos limites físicos do manômetro (0-17 BAR). Exibindo último valor válido. Verifique falha no equipamento!")
    elif status == "CHECK_VISIBILITY":
        st.warning("⚠️ ALERTA DE VISIBILIDADE: Obstruções visuais, reflexos ou sujeira detectados no visor pela câmera. Os valores abaixo podem estar incorretos!")
    elif bar_val >= 14.0:
        st.error(f"🚨 ALERTA CRÍTICO: Pressão de {bar_val:.2f} BAR excede o limite de segurança!")
        st.toast("ALERTA DE SEGURANÇA!", icon="🔥")
    else:
        st.success("🟢 Monitoramento operacional em tempo real - Leituras dentro da faixa normal.")

    # Layout de Colunas (Tempo Real)
    col1, col2 = st.columns([2, 1])

    with col1:
        st.plotly_chart(create_gauge_chart(bar_val), width='stretch')

    with col2:
        st.write("### Métricas Auxiliares (Firestore)")
        st.metric(label="Pressão Equivalente (PSI)", value=f"{psi_val:.2f} PSI")
        st.metric(label="Confiança da IA (Visão Computacional)", value=f"{confianca:.1%}")
        
        status_map = {
            "NORMAL": "🟢 Normal / Operacional",
            "CHECK_VISIBILITY": "⚠️ Verificar Visibilidade",
            "LOW_CONFIDENCE": "🚨 Baixa Confiança (Inseguro)",
            "RANGE_ERROR": "🚨 Erro Físico (Anomalia)"
        }
        status_display = status_map.get(status, "🟢 Ativo")

        st.info(f"""
        **Status do Sistema:** {status_display}  
        **Última Atualização:** {updated_at_br.strftime('%H:%M:%S')}  
        **Localização:** Caldeira Principal - Setor Sul
        """)

    st.divider()

    # --- SEÇÃO BIGQUERY HISTÓRICO DE LEITURAS ---
    st.header("🗄️ Histórico Gravado no GCP BigQuery (`telemetry_db.manometer_readings`)")
    st.write("Consultando banco de dados analítico de telemetria gravada a cada ciclo de leitura da IA.")

    df_bq = None
    if not demo_mode:
        df_bq = fetch_bigquery_history()

    if demo_mode or df_bq is None or df_bq.empty:
        if not demo_mode and (df_bq is None or df_bq.empty):
            st.info("Exibindo dados históricos de demonstração do BigQuery.")
        df_bq = get_simulated_history()

    if df_bq is not None and not df_bq.empty:
        # Métricas de Resumo do BigQuery
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric(label="Total de Leituras Gravadas", value=len(df_bq))
        with m_col2:
            st.metric(label="Pressão Média (BAR)", value=f"{df_bq['pressao_bar'].mean():.2f} BAR")
        with m_col3:
            st.metric(label="Pressão Máxima Registrada", value=f"{df_bq['pressao_bar'].max():.2f} BAR")
        with m_col4:
            st.metric(label="Média de Confiança IA", value=f"{df_bq['confianca'].mean():.1%}")

        # Gráfico de Linha do Histórico
        fig_trend = px.line(
            df_bq,
            x="timestamp",
            y="pressao_bar",
            markers=True,
            title="Evolução Temporal da Pressão (BAR) - GCP BigQuery",
            labels={"timestamp": "Data / Hora", "pressao_bar": "Pressão (BAR)"},
            line_shape="linear"
        )
        fig_trend.update_traces(line_color="#3b82f6", marker=dict(size=8, color="#10b981"))
        fig_trend.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(15,23,42,0.6)',
            font={'color': "white"},
            height=350
        )
        st.plotly_chart(fig_trend, width='stretch')

        # Tabela Detalhada com os Registros do BigQuery
        st.subheader("📋 Tabela de Registros do BigQuery")
        st.dataframe(
            df_bq.style.format({
                "pressao_bar": "{:.2f} BAR",
                "pressao_psi": "{:.2f} PSI",
                "confianca": "{:.1%}"
            }),
            width='stretch'
        )

        # Botão para Download CSV
        csv_data = df_bq.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Exportar Registros do BigQuery (CSV)",
            data=csv_data,
            file_name=f"bigquery_manometer_readings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

    # Rodapé de Monitoramento
    st.divider()
    st.caption(f"Próxima atualização em 60 segundos... | Horário local: {datetime.now(BR_TIMEZONE).strftime('%d/%m/%Y %H:%M:%S')}")

else:
    st.warning("Aguardando dados do dispositivo manometro-caldeira-01...")

# Configuração de Auto-refresh assíncrono (60 segundos)
st_autorefresh(interval=60000, key="scada_autorefresh")

