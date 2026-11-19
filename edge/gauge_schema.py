"""Esquema de saída comum a todos os backends de leitura (Gemini, Cosmos3)."""
from pydantic import BaseModel, Field


class ScaleReading(BaseModel):
    valor: float = Field(description="O valor correspondente à leitura real ou 0 se desconectado/em repouso")
    unidade: str = Field(description="A unidade da escala, em minúsculas ('bar' ou 'psi')")

class GaugeReading(BaseModel):
    raciocinio_geometrico: str = Field(description="Descrição passo a passo da análise (conexão, ponteiro físico, reflexos de dedos/mãos)")
    data_bar: ScaleReading = Field(description="Leitura convertida/medida na escala BAR")
    data_psi: ScaleReading = Field(description="Leitura convertida/medida na escala PSI")
    confianca_leitura: float = Field(description="Confiança decimal da leitura de 0.0 a 1.0")
    alerta_visibilidade: bool = Field(description="True se houver obstrução, reflexos excessivos ou se estiver desconectado")
