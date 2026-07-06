import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- CONFIGURAZIONE ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2025 Sebastiano Barusco - Tutti i diritti riservati"
DB_URL = "sqlite:///./osservatorio.db"

# --- DATABASE ENGINE ---
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
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

Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

# --- UTILS ---
def formatta_massima_sicura(m_input):
    if not m_input: return "Errore: Dati mancanti."
    if isinstance(m_input, dict):
        t = ""
        for k in ["Oggetto", "Principio di Diritto", "Ragionamento"]:
            v = m_input.get(k) or m_input.get(k.lower()) or "N/D"
            t += f"**{k.upper()}**:\n{v}\n\n"
        return t.strip()
    return str(m_input)

def pulisci_json(testo_raw):
    try:
        testo_pulito = re.sub(r'```json\s*|```', '', testo_raw).strip()
        match = re.search(r'\{.*\}', testo_pulito, re.DOTALL)
        if match: return json.loads(match.group())
        return json.loads(testo_pulito)
    except: return None

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca la chiave API su Render."
    
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # RIDUZIONE TESTO per risparmiare TOKEN: prime 2 pagine e l'ultima
        pagine = [doc[i].get_text() for i in range(min(2, len(doc)))]
        if len(doc) > 2:
            pagine.append(doc[-1].get_text())
        testo_essenziale = "\n".join(pagine).strip()
        doc.close()
        
        # PROMPT OTTIMIZZATO
        prompt = f"""Analizza questa sentenza ed estrai in JSON: organo, numero, massima: {{Oggetto, Principio di Diritto, Ragionamento}}. 
        Testo: {testo_essenziale[:6000]}"""

        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un giurista sintetico. Rispondi SOLO in JSON."},
                      {"role": "user", "content": prompt}],
            # CAMBIO MODELLO: 'llama-3.1-8b-instant' ha limiti molto più alti
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=1500
        )
        
        dati = pulisci_json(chat.choices[0].message.content)
        if dati:
            dati["massima_finale"] = formatta_massima_sicura(dati.get("massima"))
            return dati, None
        return None, "Errore nel formato dei dati."
    except Exception as e:
        return None, str(e)

# --- UI STREAMLIT ---
st.set_page_config(page_title="Osservatorio AI - Sebastiano Barusco", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione e Revisione", "📚 Archivio Storico"])

with t_gest:
    col_up, col_rev = st.columns([0.3, 0.7])
    
    with col_up:
        st.header("1. Caricamento")
        autore_f = st.text_input("Firma Redattore", value="Redazione")
        u_files = st.file_uploader("Seleziona PDF", type="pdf", accept_multiple_files=True)
        btn_avvia = st.button("🚀 AVVIA ANALISI", use_container_width=True)
        st.markdown("---")
        st.write(f"👨‍💻 **Author:** {AUTORE_SOFTWARE}")
        st.caption(COPYRIGHT_NOTE)

    with col_rev:
        st.header("2. Risultati e Revisione")
        
        if btn_avvia:
            if u_files:
                status = st.container(border=True)
                status.write("### ⏳ Analisi in corso...")
                progress = status.progress(0)
                
                for idx, u_file in enumerate(u_files):
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(u_file.getbuffer())
                    
                    status.write(f"🔍 Analizzando: {u_file.name}")
                    res, err = analizza_sentenza(path)
                    
                    if not err:
                        s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"),
                                     massima=res.get("massima_finale"), autore=autore_f, file_path=path)
                        db.add(s); db.commit()
                        status.success(f"✅ {u_file.name} pronto!")
                    else:
                        status.error(f"❌ {u_file.name}: {err}")
                    
                    progress.progress((idx + 1) / len(u_files))
                
                st.success("Analisi completata! Clicca il tasto sotto.")
                if st.button("👁️ CARICA REVISIONE"): st.rerun()
            else:
                st.warning("Carica i file!")

        # --- LISTA REVISIONE ---
        nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if nuovi:
            for s in nuovi:
                with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
                    o = st.text_input("Corte", s.organo, key=f"o{s.id}")
                    n = st.text_input("N. Sentenza", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima", s.massima, height=300, key=f"m{s.id}")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                        s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                        db.commit(); st.rerun()
                    if c2.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                        db.delete(s); db.commit(); st.rerun()
        else:
            if not btn_avvia: st.info("In attesa di documenti.")

with t_arch:
    st.subheader("📚 Archivio Sentenze Validate")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        df = pd.DataFrame([{"Organo": i.organo, "Sentenza": i.numero, "Autore": i.autore} for i in arch])
        st.dataframe(df, use_container_width=True)
        
        c1, c2 = st.columns([0.8, 0.2])
        if c2.button("⚠️ RESET"): db.query(Sentenza).delete(); db.commit(); st.rerun()
        
        st.divider()
        for i in arch:
            with st.container(border=True):
                col_a, col_b = st.columns([0.8, 0.2])
                with col_a:
                    st.markdown(f"### {i.organo}")
                    st.markdown(f"**n. {i.numero}** | *Autore: {i.autore}*")
                    st.write(i.massima)
                with col_b:
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as fp:
                            st.download_button("📂 PDF", fp, file_name=f"{i.numero}.pdf", key=f"dl_{i.id}")
    else:
        st.info("Archivio vuoto.")

db.close()
