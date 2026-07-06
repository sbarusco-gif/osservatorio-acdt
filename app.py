import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String, Text
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
def analizza_sentenza(file_path):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key: return None
    client = openai.OpenAI(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = doc[0].get_text() + "\n...\n" + doc[-1].get_text()
        doc.close()
        prompt = "Sei un esperto giurista tributario. Estrai in JSON: organo, numero, massima tecnica. NON COPIARE L'INTESTAZIONE."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e: return None

# --- UI STREAMLIT ---
st.set_page_config(page_title="ACDT AI", layout="wide")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Caricamento e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Nuova Sentenza")
        u_file = st.file_uploader("Carica PDF", type="pdf")
        if st.button("🚀 ANALIZZA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f: f.write(u_file.getbuffer())
                with st.spinner("L'IA sta lavorando..."):
                    res = analizza_sentenza(path)
                    if res:
                        s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"), massima=res.get("massima"), file_path=path)
                        db.add(s); db.commit()
                        st.success("Analisi completata!")
            else: st.error("Carica un file!")

    st.subheader("Documenti in Revisione")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    for s in nuovi:
        with st.expander(f"⚙️ MODIFICA: {s.organo} - {s.numero}", expanded=True):
            o = st.text_input("Organo", s.organo, key=f"o{s.id}")
            n = st.text_input("Numero", s.numero, key=f"n{s.id}")
            m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
            if st.button("✅ PUBBLICA", key=f"p{s.id}"):
                s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                db.commit(); st.rerun()

with t_arch:
    st.subheader("Sentenze Validate")
    if st.button("🗑️ SVUOTA TUTTO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    archivio = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for item in archivio:
        with st.container(border=True):
            st.markdown(f"**{item.organo} - n. {item.numero}**")
            st.write(item.massima)
            if os.path.exists(item.file_path):
                with open(item.file_path, "rb") as f:
                    st.download_button("📂 PDF", f, file_name=f"{item.numero}.pdf", key=f"d{item.id}")
db.close()
