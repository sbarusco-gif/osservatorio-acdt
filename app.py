python -m streamlit run app.py --server.port 10000 --server.address 0.0.0.0
import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_api_engine, Column, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import openai

# --- CONFIGURAZIONE DATABASE ---
DB_URL = "sqlite:///./osservatorio.db"
Base = declarative_base()

class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") # Nuovo, Validato
    organo = Column(String)
    numero = Column(String)
    massima = Column(String)
    file_path = Column(String)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# --- FUNZIONI AI ---
def analizza_con_ia(file_path):
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        doc = fitz.open(file_path)
        # Leggiamo inizio e fine per evitare l'intestazione
        testo = doc[0].get_text() + "\n...\n" + doc[-1].get_text()
        doc.close()

        prompt = "Sei un esperto giurista. Estrai in JSON: organo, numero, massima tecnica. NON COPIARE L'INTESTAZIONE."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Errore AI: {e}")
        return None

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="ACDT Osservatorio", layout="wide")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

t_gest, t_arch = st.tabs(["📋 Caricamento e Revisione", "📚 Archivio"])

db = SessionLocal()

with t_gest:
    with st.sidebar:
        st.header("Carica Sentenza")
        uploaded_file = st.file_uploader("Scegli un PDF", type="pdf")
        if st.button("🚀 ANALIZZA"):
            if uploaded_file:
                f_id = str(uuid.uuid4())
                f_path = f"storage/{f_id}.pdf"
                os.makedirs("storage", exist_ok=True)
                with open(f_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                with st.spinner("L'IA sta scrivendo la massima..."):
                    dati_ia = analizza_con_ia(f_path)
                    if dati_ia:
                        nuova = Sentenza(
                            id=f_id, organo=dati_ia.get("organo"), 
                            numero=dati_ia.get("numero"), 
                            massima=dati_ia.get("massima"),
                            file_path=f_path
                        )
                        db.add(nuova); db.commit()
                        st.success("Analisi completata!")
            else: st.warning("Carica un file!")

    st.subheader("Revisione Documenti")
    sentenze_nuove = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    
    if sentenze_nuove:
        for s in sentenze_nuove:
            with st.expander(f"MODIFICA: {s.organo} - {s.numero}", expanded=True):
                c1, c2 = st.columns([0.7, 0.3])
                with c1:
                    new_org = st.text_input("Organo", s.organo, key=f"org_{s.id}")
                    new_num = st.text_input("Numero", s.numero, key=f"num_{s.id}")
                    new_max = st.text_area("Massima", s.massima, height=250, key=f"max_{s.id}")
                with c2:
                    st.write("### Azioni")
                    if st.button("✅ PUBBLICA", key=f"pub_{s.id}"):
                        s.organo, s.numero, s.massima, s.stato = new_org, new_num, new_max, "Validato"
                        db.commit(); st.rerun()
                    if st.button("🗑️ ELIMINA", key=f"del_{s.id}"):
                        db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Nessuna sentenza da revisionare. Carica un file dalla colonna a sinistra.")

with t_arch:
    st.subheader("Sentenze Pubblicate")
    if st.button("⚠️ SVUOTA TUTTO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
        
    archivio = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for item in archivio:
        with st.container(border=True):
            col_a, col_b = st.columns([0.8, 0.2])
            col_a.write(f"**{item.organo} - n. {item.numero}**")
            col_a.write(item.massima)
            # Link per scaricare il PDF direttamente
            if os.path.exists(item.file_path):
                with open(item.file_path, "rb") as f:
                    col_b.download_button("📂 Scarica PDF", f, file_name=f"{item.numero}.pdf")

db.close()
