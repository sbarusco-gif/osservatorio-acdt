import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- DATABASE CONFIG ---
DB_URL = "sqlite:///./osservatorio.db"
Base = declarative_base()

class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String)
    numero = Column(String)
    massima = Column(String) 
    file_path = Column(String)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# --- UTILS ---
def formatta_massima(m_input):
    if isinstance(m_input, dict):
        testo = ""
        for chiave, valore in m_input.items():
            testo += f"{chiave.upper()}:\n{valore}\n\n"
        return testo.strip()
    return str(m_input)

def pulisci_json(testo_raw):
    try:
        testo_pulito = re.sub(r'```json\s*|```', '', testo_raw).strip()
        match = re.search(r'\{.*\}', testo_pulito, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(testo_pulito)
    except:
        return None

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca GROQ_API_KEY."
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        pagine = [doc[i].get_text() for i in range(min(6, len(doc)))]
        if len(doc) > 6: pagine.append(doc[-1].get_text())
        testo_estratto = "\n".join(pagine).strip()
        doc.close()
        if len(testo_estratto) < 200: return None, "PDF non leggibile."

        prompt = f"""Analizza questa sentenza tributaria e redigi una MASSIMA GIURIDICA ESTESA.
        Restituisci ESCLUSIVAMENTE un oggetto JSON con:
        - "organo": nome della corte
        - "numero": numero/anno
        - "massima": {{
            "Oggetto": "...",
            "Principio di Diritto": "...",
            "Ragionamento": "..."
          }}
        TESTO: {testo_estratto[:15000]}"""

        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un esperto giurista. Rispondi in JSON puro."},
                      {"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=3000
        )
        dati = pulisci_json(chat.choices[0].message.content)
        if not dati: return None, "Errore formato JSON."
        dati["massima_str"] = formatta_massima(dati.get("massima"))
        return dati, None
    except Exception as e: return None, str(e)

# --- INTERFACCIA ---
st.set_page_config(page_title="Osservatorio AI", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Caricamento Multiplo")
        u_files = st.file_uploader("Trascina qui i PDF", type="pdf", accept_multiple_files=True)
        if st.button("🚀 ELABORA TUTTE"):
            if u_files:
                progress = st.progress(0)
                for index, u_file in enumerate(u_files):
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(u_file.getbuffer())
                    res, err = analizza_sentenza(path)
                    if not err:
                        s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"), massima=res.get("massima_str"), file_path=path)
                        db.add(s); db.commit()
                    progress.progress((index + 1) / len(u_files))
                st.success("Completato!"); time.sleep(1); st.rerun()
            else: st.warning("Carica i file!")

    st.subheader("Massime da Revisionare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"📝 {s.organo} - {s.numero}"):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima", s.massima, height=300, key=f"m{s.id}")
                if st.button("✅ PUBBLICA", key=f"p{s.id}"):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
