import streamlit as st
import os, uuid, fitz, json, time, re
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- DATABASE ---
DB_URL = "sqlite:///./osservatorio.db"
Base = declarative_base()
class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String); numero = Column(String); massima = Column(String); file_path = Column(String)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# --- FUNZIONE DI PULIZIA JSON ---
def pulisci_json(testo_raw):
    """Estrae il JSON puro anche se l'IA aggiunge commenti o backticks"""
    try:
        match = re.search(r'\{.*\}', testo_raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(testo_raw)
    except:
        return None

# --- ANALISI IA ---
def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca GROQ_API_KEY su Render."
    
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Leggiamo più testo per sicurezza (prime 4 pagine + ultima)
        testo_pagine = []
        for i in range(min(4, len(doc))):
            testo_pagine.append(doc[i].get_text())
        if len(doc) > 4:
            testo_pagine.append(doc[-1].get_text())
        
        testo_completo = "\n".join(testo_pagine).strip()
        doc.close()
        
        if len(testo_completo) < 100:
            return None, "Il PDF sembra un'immagine (scansione). L'IA non può leggere il testo."

        prompt = f"""Analizza questa sentenza tributaria. 
        Estrai ESATTAMENTE questi campi in formato JSON:
        - "organo": il nome della Corte/Commissione
        - "numero": il numero della sentenza e l'anno
        - "massima": un breve principio di diritto (massima tecnica)
        
        Documento:
        {testo_completo[:10000]}"""

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Rispondi solo in JSON. Non aggiungere introduzioni."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1
        )
        
        risultato_raw = chat.choices[0].message.content
        dati = pulisci_json(risultato_raw)
        
        if not dati:
            return None, "L'IA ha risposto in un formato non leggibile. Riprova."
            
        return dati, None
    except Exception as e:
        return None, f"Errore tecnico: {str(e)}"

# --- UI ---
st.set_page_config(page_title="ACDT Osservatorio", layout="wide")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Revisione", "📚 Archivio"])

with t_gest:
    with st.sidebar:
        st.header("Carica PDF")
        u_file = st.file_uploader("Seleziona file", type="pdf")
        if st.button("🚀 ANALIZZA ORA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f: f.write(u_file.getbuffer())
                
                with st.spinner("Analisi in corso..."):
                    res, err = analizza_sentenza(path)
                    if err:
                        st.error(err)
                    else:
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "Non trovato"), 
                            numero=res.get("numero", "Non trovato"), 
                            massima=res.get("massima", "Non trovata"), 
                            file_path=path
                        )
                        db.add(s); db.commit()
                        st.success("Analisi completata!")
                        time.sleep(1); st.rerun()
            else: st.warning("Carica un file!")

    st.subheader("Revisione Documenti")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    for s in nuovi:
        with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
            o = st.text_input("Organo", s.organo, key=f"o{s.id}")
            n = st.text_input("Numero", s.numero, key=f"n{s.id}")
            m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
            c1, c2 = st.columns(2)
            if c1.button("✅ PUBBLICA", key=f"p{s.id}"):
                s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                db.commit(); st.rerun()
            if c2.button("🗑️ ELIMINA", key=f"d{s.id}"):
                db.delete(s); db.commit(); st.rerun()

with t_arch:
    st.subheader("Archivio Storico")
    if st.button("⚠️ SVUOTA"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.write(f"**{i.organo} - n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 PDF", f, file_name=f"{i.numero}.pdf", key=i.id)
db.close()
