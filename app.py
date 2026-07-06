import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import openai

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

# --- FUNZIONE ANALISI AI ---
def analizza_sentenza(file_path):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "ERRORE: Manca la chiave OPENAI_API_KEY nelle impostazioni di Render."
    
    client = openai.OpenAI(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        if len(doc) == 0:
            return None, "ERRORE: Il file PDF sembra vuoto."
        
        # Estraiamo testo da inizio e fine per i dati e il principio di diritto
        testo = doc[0].get_text() + "\n" + doc[-1].get_text()
        doc.close()
        
        if len(testo.strip()) < 50:
            return None, "ERRORE: Il PDF non contiene testo leggibile (forse è una scansione immagine)."

        prompt = "Sei un esperto giurista tributario. Estrai in JSON: organo, numero, massima tecnica (astratta). NON COPIARE L'INTESTAZIONE."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": testo[:8000]}
            ],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content), None
    except Exception as e:
        return None, f"ERRORE AI: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="ACDT AI", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Revisione", "📚 Archivio"])

with t_gest:
    with st.sidebar:
        st.header("Carica Sentenza")
        u_file = st.file_uploader("Trascina qui il PDF", type="pdf")
        if st.button("🚀 ANALIZZA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f:
                    f.write(u_file.getbuffer())
                
                with st.spinner("L'IA sta analizzando il documento..."):
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
                        db.add(s)
                        db.commit()
                        st.success("Analisi completata!")
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("Seleziona un file PDF.")

    st.subheader("Documenti da convalidare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    
    if nuovi:
        for s in nuovi:
            # QUESTA È LA RIGA CHE DAVA ERRORE - ASSICURATI CHE SIA COMPLETA
            with st.expander(f"⚙️ MODIFICA: {s.organo} - {s.numero}", expanded=True):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
                
                c1, c2 = st.columns(2)
                if c1.button("✅ PUBBLICA", key=f"p{s.id}"):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit()
                    st.rerun()
                if c2.button("🗑️ ELIMINA", key=f"d{s.id}"):
                    db.delete(s)
                    db.commit()
                    st.rerun()
    else:
        st.info("Nessuna sentenza in attesa.")

with t_arch:
    st.subheader("Sentenze Validate")
    if st.button("⚠️ SVUOTA ARCHIVIO"):
        db.query(Sentenza).delete()
        db.commit()
        st.rerun()
    
    archivio = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for item in archivio:
        with st.container(border=True):
            col1, col2 = st.columns([0.8, 0.2])
            col1.markdown(f"**{item.organo} - n. {item.numero}**")
            col1.write(item.massima)
            if os.path.exists(item.file_path):
                with open(item.file_path, "rb") as f:
                    col2.download_button("📂 PDF", f, file_name=f"{item.numero}.pdf", key=f"btn_{item.id}")

db.close()
