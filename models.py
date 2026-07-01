import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, Text, Numeric, JSON, Date, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from database import Base  # <--- ASSICURATI CHE NON CI SIA IL PUNTO QUI
import enum

class StatoFascicolo(enum.Enum):
    Caricato = "Caricato"
    In_estrazione = "In estrazione"
    Da_validare = "Da validare"
    Validato = "Validato"
    Respinto = "Respinto"
    Pubblicato = "Pubblicato"

class EsitoSentenza(enum.Enum):
    Accolto = "Accolto"
    Respinto = "Respinto"
    Parzialmente_accolto = "Parzialmente accolto"
    Altro = "Altro"

class Tributo(Base):
    __tablename__ = "tributi"
    id = Column(Integer, primary_key=True, index=True)
    denominazione = Column(String, unique=True, nullable=False)
    stato = Column(String, default="Proposto")

class Fascicolo(Base):
    __tablename__ = "fascicoli"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stato = Column(Enum(StatoFascicolo), default=StatoFascicolo.Caricato)
    file_originale = Column(Text, nullable=False)
    data_caricamento = Column(DateTime(timezone=True), server_default=func.now())

class Scheda(Base):
    __tablename__ = "schede"
    id_fascicolo = Column(UUID(as_uuid=True), ForeignKey("fascicoli.id"), primary_key=True)
    organo_ai = Column(Text)
    organo_corrente = Column(Text)
    numero_sentenza_ai = Column(Text)
    numero_sentenza_corrente = Column(Text)
    data_deposito_ai = Column(Date)
    data_deposito_corrente = Column(Date)
    esito_ai = Column(Enum(EsitoSentenza))
    esito_corrente = Column(Enum(EsitoSentenza))
    massima_ai = Column(Text)
    massima_corrente = Column(Text)
    note_riservate = Column(Text)
    punteggio_confidenza = Column(Numeric(5, 2))
    versione_modello = Column(String(50))