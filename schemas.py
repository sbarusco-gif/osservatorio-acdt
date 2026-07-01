from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List
from uuid import UUID

class SchedaBase(BaseModel):
    id_fascicolo: UUID
    organo_ai: Optional[str]
    numero_sentenza_ai: Optional[str]
    data_deposito_ai: Optional[date]
    massima_ai: Optional[str]
    esito_ai: Optional[str]
    class Config:
        from_attributes = True

class FascicoloBase(BaseModel):
    id: UUID
    stato: str
    file_originale: str
    data_caricamento: datetime
    class Config:
        from_attributes = True

# QUESTO DEVE ESSERE ESATTAMENTE COSÌ:
class ValidazioneInput(BaseModel):
    organo: Optional[str] = None
    numero_sentenza: Optional[str] = None
    data_deposito: Optional[date] = None
    esito: Optional[str] = None
    massima: Optional[str] = None
    note_riservate: Optional[str] = None
    tributo: Optional[str] = None # Aggiunto tributo