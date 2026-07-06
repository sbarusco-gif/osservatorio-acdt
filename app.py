import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- INFO AUTORE E COPYRIGHT ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2025 Sebastiano Barusco - Tutti i diritti riservati"

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
    autore = Column(String)
    file_path = Column(String)

# Creazione engine con gestione errori
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# --- UTILS ---
def formatta_massima_sicura(m_input):
    if not m_input:
        return "Errore: L'IA non ha generato la massima."
    if isinstance(m_input, dict):
        testo = ""
        for k in ["Oggetto", "Principio di Diritto", "Ragionamento"]:
            v = m_input.get(k) or m_input.get(k.lower()) or "Non rilevato"
            testo += f"**{k.upper()}**:\n{v}\n\n"
        return testo.strip()
    return str(m_input)

def pulisci_json(testo_raw):
    try:
        # Rimuove i blocchi di codice markdown
        testo_pulito = re.sub(r'```json\s*|```', '', testo_raw).strip()
        match = re.search(r'\{.*\}', testo_pulito, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(testo_pulito)
    except Exception as e:
        return None

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: 
        return None, "MANCA CHIAVE: Inserisci GROQ_API_KEY nelle impostazioni di Render."
    
    client = Groq(api_key=api_key)
    try:
        # Estrazione testo PDF
        doc = fitz.open(file_path)
        testo_estratto = ""
        for i in range(min(6, len(doc))):
            testo_estratto += doc[i].get_text()
        testo_estratto += "\n" + doc[-1].get_text()
        doc.close()
        
        if len(testo_estratto.strip()) < 100:
            return None, "PDF ILLEGGIBILE: Il file sembra una scansione immagine senza testo."

        prompt = f"""Analizza questa sentenza tributaria ed estrai in JSON:
        - "organo": nome corte
        - "numero": numero/anno
        - "massima": {{"Oggetto": "...", "Principio di Diritto": "...", "Ragionamento": "..."}}
        Testo: {testo_estratto[:12000]}"""

        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un massimario esperto. Rispondi solo in JSON."},
                      {"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.1
        )
        
        res_raw = chat.choices[0].message.content
        dati = pulisci_json(res_raw)
        
        if not dati:
            return None, "ERRORE FORMATO: L'IA ha risposto ma il JSON è corrotto."
        
        dati["massima_finale"] = formatta_massima_sicura(dati.get("massima"))
        return dati, None

    except Exception as e:
        return None, f"ERRORE API GROQ: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="Osservatorio - Sebastiano Barusco", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Caricamento")
        autore_firma = st.text_input("Firma Caricamento", value="Redazione")
        u_files = st.file_uploader("Seleziona uno o più PDF", type="pdf", accept_multiple_files=True)
        
        if st.button("🚀 ELABORA SENTENZE"):
            if u_files:
                progress = st.progress(0)
                for idx, u_file in enumerate(u_files):
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(u_file.getbuffer())
                    
                    st.toast(f"Analisi di: {u_file.name}")
                    res, err = analizza_sentenza(path)
                    
                    if not err:
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "N/D"), 
                            numero=res.get("numero", "N/D"),
                            massima=res.get("massima_finale"), 
                            autore=autore_firma, 
                            file_path=path
                        )
                        db.add(s)
                        db.commit()
                    else:
                        st.error(f"Errore su {u_file.name}: {err}")
                    
                    progress.progress((idx + 1) / len(u_files))
                st.rerun()
            else:
                st.warning("Seleziona almeno un file PDF.")
        
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"👨‍💻 **Software Author:**\n**{AUTORE_SOFTWARE}**")
        st.sidebar.caption(COPYRIGHT_NOTE)

    st.subheader("Massime da Revisionare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"📝 {s.organo} - {s.numero}", expanded=False):
                c1, c2 = st.columns([0.7, 0.3])
                with c1:
                    o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                    n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima", s.massima, height=350, key=f"m{s.id}")
                with c2:
                    aut = st.text_input("Firma", s.autore, key=f"a{s.id}")
                    if st.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                        s.organo, s.numero, s.massima, s.autore, s.stato = o, n, m, aut, "Validato"
                        db.commit(); st.rerun()
                    if st.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                        db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Carica i PDF dalla barra laterale per iniziare l'analisi.")

with t_arch:
    st.subheader("Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
        df = pd.DataFrame([{"Organo": i.organo, "Sentenza": i.numero, "Massima": i.massima.replace("**", ""), "Autore": i.autore} for i in arch])
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Archivio')
        c1.download_button("📊 SCARICA EXCEL", data=output.getvalue(), file_name="osservatorio.xlsx", use_container_width=True)
        
        if c3.button("⚠️ SVUOTA ARCHIVIO", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
        
        st.divider()
        for i in arch:
            with st.container(border=True):
                col_a, col_b = st.columns([0.8, 0.2])
                with col_a:
                    st.markdown(f"### {i.organo}")
                    st.markdown(f"**Sentenza n. {i.numero}** | *Firma: {i.autore}*")
                    st.write(i.massima)
                with col_b:
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as f_pdf:
                            st.download_button("📂 PDF", f_pdf, file_name=f"sentenza_{i.numero}.pdf", key=f"dl_{i.id}")
    else:
        st.info("L'archivio è vuoto. Valida le sentenze nella scheda 'Gestione'.")

st.markdown("---")
st.caption(f"🚀 {AUTORE_SOFTWARE} | {COPYRIGHT_NOTE}")
db.close()
