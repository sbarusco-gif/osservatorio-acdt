import streamlit as st
import os, uuid, fitz, json, time, re
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
            testo += f"**{chiave.upper()}**:\n{valore}\n\n"
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

# --- ANALISI IA ---
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
        
        if len(testo_estratto) < 200:
            return None, "PDF non leggibile (scansione/immagine)."

        prompt = f"""Analizza questa sentenza tributaria e redigi una MASSIMA GIURIDICA ESTESA.
        Restituisci ESCLUSIVAMENTE un oggetto JSON con:
        - "organo": nome della corte
        - "numero": numero/anno
        - "massima": {{
            "Oggetto": "...",
            "Principio di Diritto": "...",
            "Ragionamento": "..."
          }}

        DOCUMENTO:
        {testo_estratto[:15000]}"""

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sei un esperto giurista tributario. Rispondi in JSON puro."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=3000
        )
        
        dati = pulisci_json(chat.choices[0].message.content)
        if not dati: return None, "Errore formato JSON."
        
        dati["massima_str"] = formatta_massima(dati.get("massima"))
        return dati, None
    except Exception as e:
        return None, str(e)

# --- INTERFACCIA ---
st.set_page_config(page_title="Osservatorio AI Multiplo", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Caricamento Multiplo")
        # Abilitato accept_multiple_files
        u_files = st.file_uploader("Trascina qui uno o più PDF", type="pdf", accept_multiple_files=True)
        
        if st.button("🚀 ELABORA TUTTE LE SENTENZE"):
            if u_files:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for index, u_file in enumerate(u_files):
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    
                    status_text.text(f"Analisi file {index+1}/{len(u_files)}: {u_file.name}...")
                    
                    with open(path, "wb") as f: f.write(u_file.getbuffer())
                    
                    res, err = analizza_sentenza(path)
                    if not err:
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "N/D"), 
                            numero=res.get("numero", "N/D"), 
                            massima=res.get("massima_str", "N/D"), 
                            file_path=path
                        )
                        db.add(s)
                        db.commit()
                    else:
                        st.sidebar.error(f"Errore su {u_file.name}: {err}")
                    
                    progress_bar.progress((index + 1) / len(u_files))
                
                status_text.text("✅ Caricamento completato!")
                time.sleep(2)
                st.rerun()
            else:
                st.warning("Carica almeno un file!")

    st.subheader("Massime da Revisionare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        st.write(f"Hai **{len(nuovi)}** sentenze in attesa di revisione.")
        for s in nuovi:
            with st.expander(f"📝 {s.organo} - {s.numero}", expanded=False):
                col_edit, col_actions = st.columns([0.8, 0.2])
                with col_edit:
                    o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                    n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima Estesa", s.massima, height=350, key=f"m{s.id}")
                with col_actions:
                    st.write("###")
                    if st.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                        s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                        db.commit(); st.rerun()
                    if st.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                        db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Nessuna sentenza da revisionare.")

with t_arch:
    st.subheader("Archivio Storico")
    c1, c2 = st.columns([0.8, 0.2])
    with c2:
        if st.button("⚠️ SVUOTA TUTTO", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
    
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"### {i.organo}")
            st.markdown(f"**Sentenza n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 PDF", f, file_name=f"{i.numero}.pdf", key=i.id)

db.close()
