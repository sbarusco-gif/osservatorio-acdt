import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import anthropic  # Passaggio ad Anthropic

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

# --- FUNZIONE ANALISI CON CLAUDE ---
def analizza_sentenza(file_path):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ERRORE: Manca la chiave ANTHROPIC_API_KEY nelle impostazioni di Render."
    
    client = anthropic.Anthropic(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Leggiamo inizio e fine del documento
        testo = doc[0].get_text() + "\n" + doc[-1].get_text()
        doc.close()
        
        if len(testo.strip()) < 50:
            return None, "ERRORE: PDF non leggibile (scansione immagine)."

        prompt = """Sei un esperto giurista tributario. Analizza la sentenza ed estrai la massima tecnica.
        Restituisci esclusivamente un oggetto JSON con queste chiavi:
        "organo": nome della commissione o corte,
        "numero": numero sentenza/anno,
        "massima": il principio di diritto stabilito (tecnico e asciutto).
        Non aggiungere commenti prima o dopo il JSON."""

        # Chiamata a Claude 3.5 Sonnet
        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=1000,
            temperature=0,
            system=prompt,
            messages=[
                {"role": "user", "content": f"Ecco il testo: {testo[:10000]}"}
            ]
        )
        
        # Estrazione e pulizia del JSON dalla risposta di Claude
        response_text = message.content[0].text
        dati = json.loads(response_text)
        return dati, None
    except Exception as e:
        return None, f"ERRORE CLAUDE: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="ACDT AI - Claude", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria (Claude 3.5)")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Revisione", "📚 Archivio"])

with t_gest:
    with st.sidebar:
        st.header("Carica Sentenza")
        u_file = st.file_uploader("Trascina qui il PDF", type="pdf")
        if st.button("🚀 ANALIZZA CON CLAUDE"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f:
                    f.write(u_file.getbuffer())
                
                with st.spinner("Claude sta analizzando la sentenza..."):
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
                        time.sleep(1)
                        st.rerun()
            else:
                st.warning("Seleziona un file.")

    st.subheader("Documenti da convalidare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"MODIFICA: {s.organo} - {s.numero}", expanded=True):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
                c1, c2 = st.columns(2)
                if c1.button("✅ PUBBLICA", key=f"p{s.id}"):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit(); st.rerun()
                if c2.button("🗑️ ELIMINA", key=f"d{s.id}"):
                    db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Nessuna sentenza in attesa.")

with t_arch:
    st.subheader("Sentenze Validate")
    if st.button("⚠️ SVUOTA ARCHIVIO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"**{i.organo} - n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 PDF", f, file_name=f"{i.numero}.pdf", key=i.id)

db.close()
