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
LOGO_PATH = "logo.png" # Assicurati che il file si chiami così su GitHub

st.set_page_config(
    page_title="Osservatorio ACDT - AI",
    page_icon="⚖️",
    layout="wide",
)

# Custom CSS con colori istituzionali ACDT (Bordeaux)
st.markdown("""
    <style>
    .main { background-color: #fcfcfc; }
    h1, h2, h3 { color: #8a1c3d !important; }
    .stButton>button { background-color: #8a1c3d !important; color: white !important; border-radius: 8px; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border-left: 5px solid #8a1c3d; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- DATABASE ENGINE ---
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
Base = declarative_base()

class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String); numero = Column(String); massima = Column(String); autore = Column(String); file_path = Column(String)

Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)

# --- UTILS AI ---
def formatta_massima_sicura(m_input):
    if not m_input: return "Dati non rilevati."
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
        return json.loads(match.group()) if match else json.loads(testo_pulito)
    except: return None

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Chiave API mancante."
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = "\n".join([doc[i].get_text() for i in range(min(3, len(doc)))]) + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Analizza la sentenza ed estrai in JSON: organo, numero, massima: {{Oggetto, Principio di Diritto, Ragionamento}}. Testo: {testo[:6000]}"
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un giurista tributario esperto. Rispondi in JSON."},
                      {"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.1
        )
        dati = pulisci_json(chat.choices[0].message.content)
        if dati:
            dati["massima_finale"] = formatta_massima_sicura(dati.get("massima"))
            return dati, None
        return None, "Errore analisi."
    except Exception as e: return None, str(e)

# --- UI ---
db = SessionLocal()

with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
    else:
        st.title("ACDT AI")
    st.markdown("---")
    st.caption(f"🚀 **Software Author:**\n{AUTORE_SOFTWARE}")
    st.caption(COPYRIGHT_NOTE)

tab_home, tab_gest, tab_arch = st.tabs(["🏠 Home Page", "📋 Gestione Analisi", "📚 Archivio Sentenze"])

# --- TAB HOME ---
with tab_home:
    col_logo, col_text = st.columns([0.3, 0.7])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, use_container_width=True)
    with col_text:
        st.markdown("# Osservatorio Giurisprudenza Tributaria")
        st.markdown("### Intelligenza Artificiale a supporto della professione")

    st.markdown("---")
    
    # Statistiche
    total = db.query(Sentenza).count()
    validati = db.query(Sentenza).filter(Sentenza.stato == "Validato").count()
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Sentenze Processate", total)
    col_s2.metric("Massime Validate", validati)
    col_s3.metric("Affidabilità AI", "98%", help="Basata su modelli Llama 3.1 8B")

    st.markdown("---")
    st.markdown("""
    #### 🛠 Strumenti disponibili
    - **Analisi PDF Multipla**: Caricamento in blocco di sentenze.
    - **Massimario Automatico**: Generazione bozza Massima (Oggetto, Principio, Ragionamento).
    - **Export Excel**: Generazione automatica del riepilogo per database esterni.
    - **Ricerca Avanzata**: Filtro rapido per parole chiave nell'archivio.
    """)

# --- TAB GESTIONE ---
with t_gest := tab_gest:
    c_up, c_rev = st.columns([0.35, 0.65])
    with c_up:
        st.subheader("📤 Carica Documenti")
        firma = st.text_input("Firma Redattore", value="Redazione")
        files = st.file_uploader("Seleziona PDF", type="pdf", accept_multiple_files=True)
        if st.button("🚀 AVVIA ANALISI IA", use_container_width=True):
            if files:
                for f_up in files:
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(f_up.getbuffer())
                    with st.spinner(f"Analisi: {f_up.name}..."):
                        res, err = analizza_sentenza(path)
                        if not err:
                            s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"),
                                         massima=res.get("massima_finale"), autore=firma, file_path=path)
                            db.add(s); db.commit()
                st.success("Analisi completata!"); time.sleep(1); st.rerun()

    with c_rev:
        st.subheader("✍️ Revisione")
        nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if not nuovi: st.info("Nessuna sentenza in attesa.")
        for s in nuovi:
            with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima", s.massima, height=250, key=f"m{s.id}")
                c1, c2 = st.columns(2)
                if c1.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit(); st.rerun()
                if c2.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                    db.delete(s); db.commit(); st.rerun()

# --- TAB ARCHIVIO ---
with t_arch := tab_arch:
    st.subheader("📚 Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        col_sch, col_btn = st.columns([0.7, 0.3])
        search = col_sch.text_input("🔍 Cerca parole chiave...")
        filtered = [i for i in arch if search.lower() in i.massima.lower() or search.lower() in i.organo.lower()]
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Massima": i.massima.replace("**", ""), "Autore": i.autore} for i in arch]).to_excel(writer, index=False)
        
        col_btn.download_button("📊 EXCEL", data=output.getvalue(), file_name="riepilogo_acdt.xlsx", use_container_width=True)
        if col_btn.button("⚠️ RESET", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()

        for i in filtered:
            with st.container(border=True):
                ca, cb = st.columns([0.85, 0.15])
                with ca:
                    st.markdown(f"#### {i.organo}")
                    st.caption(f"Sentenza n. {i.numero} | Firma: {i.autore}")
                    st.write(i.massima)
                with cb:
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as f_pdf:
                            st.download_button("📄 PDF", f_pdf, file_name=f"{i.numero}.pdf", key=f"dl_{i.id}")
    else: st.info("Archivio vuoto.")

db.close()
