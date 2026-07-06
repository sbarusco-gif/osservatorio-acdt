import streamlit as st
import os, uuid, fitz, json, time
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import openai

# --- CONFIGURAZIONE DATABASE (SQLITE) ---
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
        return {"organo": "ERRORE", "numero": "MANCA API KEY", "massima": "Configura OPENAI_API_KEY su Render."}
    
    client = openai.OpenAI(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Legge solo le parti cruciali per evitare l'intestazione
        testo = doc[0].get_text()[:4000] + "\n...\n" + doc[-1].get_text()[:4000]
        doc.close()

        prompt = "Sei un esperto giurista. Estrai in JSON: organo, numero, massima tecnica. NON COPIARE L'INTESTAZIONE."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo}],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"organo": "Errore", "numero": "Errore", "massima": str(e)}

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="ACDT AI", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()

t_gest, t_arch = st.tabs(["📋 Caricamento e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Nuovo PDF")
        u_file = st.file_uploader("Trascina qui la sentenza", type="pdf")
        if st.button("🚀 ANALIZZA CON IA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                f_path = f"storage/{f_id}.pdf"
                with open(f_path, "wb") as f:
                    f.write(u_file.getbuffer())
                
                with st.spinner("L'IA sta leggendo la sentenza..."):
                    res = analizza_sentenza(f_path)
                    nuova = Sentenza(
                        id=f_id, organo=res.get("organo"), 
                        numero=res.get("numero"), 
                        massima=res.get("massima"),
                        file_path=f_path
                    )
                    db.add(nuova); db.commit()
                st.success("Completato! Guarda a destra.")
            else: st.error("Carica un file!")

    st.subheader("Documenti da Revisionare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"⚙️ MODIFICA: {s.organo} - {s.numero}", expanded=True):
                c1, c2 = st.columns([0.7, 0.3])
                with c1:
                    ed_org = st.text_input("Organo", s.organo, key=f"o_{s.id}")
                    ed_num = st.text_input("Numero", s.numero, key=f"n_{s.id}")
                    ed_max = st.text_area("Massima", s.massima, height=200, key=f"m_{s.id}")
                with c2:
                    st.write("### Azioni")
                    if st.button("✅ PUBBLICA", key=f"p_{s.id}"):
                        s.organo, s.numero, s.massima, s.stato = ed_org, ed_num, ed_max, "Validato"
                        db.commit(); st.rerun()
                    if st.button("🗑️ ELIMINA", key=f"d_{s.id}"):
                        db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Nessuna sentenza in attesa. Carica un PDF dal menu a sinistra.")

with t_arch:
    st.subheader("Sentenze Validate")
    if st.button("⚠️ SVUOTA ARCHIVIO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
        
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
