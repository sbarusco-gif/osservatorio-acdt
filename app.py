import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import openai

# --- DATABASE ---
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

# --- LOGICA AI ---
def analizza_ia(file_path):
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    try:
        doc = fitz.open(file_path)
        testo = doc[0].get_text() + "\n...\n" + doc[-1].get_text()
        doc.close()
        prompt = "Sei un esperto giurista tributario. Estrai in JSON: organo, numero, massima tecnica (astratta). NON COPIARE L'INTESTAZIONE."
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
            response_format={ "type": "json_object" }
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {"organo": "Errore", "numero": "Errore", "massima": str(e)}

# --- INTERFACCIA ---
st.set_page_config(page_title="ACDT Osservatorio", layout="wide")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Revisione", "📚 Archivio"])

with t_gest:
    with st.sidebar:
        st.header("Carica Sentenza")
        file = st.file_uploader("PDF Sentenza", type="pdf")
        if st.button("🚀 ANALIZZA"):
            if file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f: f.write(file.getbuffer())
                with st.spinner("L'IA sta lavorando..."):
                    res = analizza_ia(path)
                    s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"), massima=res.get("massima"), file_path=path)
                    db.add(s); db.commit()
                st.success("Fatto! Controlla a destra.")
            else: st.error("Carica un file!")

    st.subheader("Documenti da convalidare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    for s in nuovi:
        with st.expander(f"MODIFICA: {s.organo} - {s.numero}", expanded=True):
            o = st.text_input("Organo", s.organo, key=f"o{s.id}")
            n = st.text_input("Numero", s.numero, key=f"n{s.id}")
            m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
            if st.button("✅ PUBBLICA", key=f"p{s.id}"):
                s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                db.commit(); st.rerun()

with t_arch:
    st.subheader("Archivio Storico")
    if st.button("🗑️ SVUOTA TUTTO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"**{i.organo} - n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 Scarica PDF", f, file_name=f"{i.numero}.pdf", key=i.id)
db.close()
