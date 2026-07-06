import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq  # Nuova libreria Groq

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

# --- FUNZIONE ANALISI CON GROQ (GRATIS) ---
def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None, "ERRORE: Manca la chiave GROQ_API_KEY su Render."
    
    client = Groq(api_key=api_key)
    
    try:
        doc = fitz.open(file_path)
        # Leggiamo le parti salienti
        testo = doc[0].get_text() + "\n...\n" + doc[-1].get_text()
        doc.close()
        
        prompt = f"""Analizza questa sentenza tributaria italiana ed estrai i dati in formato JSON.
        REGOLE: 
        1. Estrai l'organo giudicante.
        2. Estrai il numero della sentenza e l'anno.
        3. Scrivi una massima tecnica e astratta (principio di diritto).
        4. Rispondi ESCLUSIVAMENTE con il JSON.
        
        TESTO: {testo[:8000]}"""

        # Usiamo Llama 3.1 70B (molto potente per il diritto)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sei un esperto giurista che risponde solo in JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-70b-versatile",
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        dati = json.loads(chat_completion.choices[0].message.content)
        return dati, None
    except Exception as e:
        return None, f"ERRORE GROQ: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="Osservatorio Groq", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria (Llama 3.1)")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Revisione", "📚 Archivio"])

with t_gest:
    with st.sidebar:
        st.header("Upload")
        u_file = st.file_uploader("Carica PDF", type="pdf")
        if st.button("🚀 ANALISI SUPER VELOCE"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f:
                    f.write(u_file.getbuffer())
                
                with st.spinner("Analisi ultra-rapida in corso..."):
                    risultato, errore = analizza_sentenza(path)
                    if errore:
                        st.error(errore)
                    else:
                        s = Sentenza(
                            id=f_id, 
                            organo=risultato.get("organo", "N/D"), 
                            numero=risultato.get("numero", "N/D"), 
                            massima=risultato.get("massima", "N/D"), 
                            file_path=path
                        )
                        db.add(s); db.commit()
                        st.success("Analisi completata!")
                        time.sleep(1); st.rerun()
            else:
                st.warning("Carica un file.")

    st.subheader("Revisione")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"MODIFICA: {s.organo} - {s.numero}", expanded=True):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
                col1, col2 = st.columns(2)
                if col1.button("✅ PUBBLICA", key=f"p{s.id}"):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit(); st.rerun()
                if col2.button("🗑️ ELIMINA", key=f"d{s.id}"):
                    db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Nessuna sentenza in attesa.")

with t_arch:
    st.subheader("Archivio")
    if st.button("⚠️ SVUOTA"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    
    archivio = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for item in archivio:
        with st.container(border=True):
            st.write(f"**{item.organo} - n. {item.numero}**")
            st.write(item.massima)
            if os.path.exists(item.file_path):
                with open(item.file_path, "rb") as f:
                    st.download_button("📂 PDF", f, file_name=f"{item.numero}.pdf", key=item.id)

db.close()
