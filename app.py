import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String
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

# --- FUNZIONE ANALISI AI (CON DIAGNOSTICA) ---
def analizza_sentenza(file_path):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "ERRORE: Manca la chiave OPENAI_API_KEY nelle impostazioni di Render."
    
    client = openai.OpenAI(api_key=api_key)
    try:
        # 1. Prova a leggere il PDF
        doc = fitz.open(file_path)
        if len(doc) == 0:
            return None, "ERRORE: Il file PDF sembra vuoto o danneggiato."
        
        # Prendi testo da inizio e fine
        testo = doc[0].get_text() + "\n" + doc[-1].get_text()
        doc.close()
        
        if len(testo.strip()) < 50:
            return None, "ERRORE: Non riesco a leggere testo nel PDF. Potrebbe essere una scansione (immagine). Serve un PDF testuale."

        # 2. Chiama l'IA
        prompt = "Sei un esperto giurista tributario. Estrai in JSON: organo, numero, massima tecnica (astratta). NON COPIARE L'INTESTAZIONE."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo[:8000]}],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content), None
    except openai.AuthenticationError:
        return None, "ERRORE: La chiave OpenAI non è valida o è scaduta."
    except openai.RateLimitError:
        return None, "ERRORE: Hai esaurito i crediti sul tuo account OpenAI."
    except Exception as e:
        return None, f"ERRORE IMPREVISTO: {str(e)}"

# --- INTERFACCIA ---
st.set_page_config(page_title="ACDT AI", layout="wide")
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
                        db.add(s); db.commit()
                        st.success("Analisi completata con successo!")
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("Seleziona un file PDF prima di cliccare.")

    st.subheader("Documenti da convalidare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.e
