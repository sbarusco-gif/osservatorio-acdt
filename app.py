import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq
from docx import Document
from docx.shared import Pt, RGBColor

# --- CONFIGURAZIONE PERCORSI (RENDER DISK) ---
IS_RENDER = os.environ.get("RENDER", False)
# Percorso aggiornato a /data per evitare PermissionError
BASE_DIR = "/data" if IS_RENDER else "./data"
DB_PATH = os.path.join(BASE_DIR, "osservatorio_final.db")
STORAGE_DIR = os.path.join(BASE_DIR, "sentenze_pdf")
LOGO_PATH = "logo.png"

if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR, exist_ok=True)

# --- INFO AUTORE ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2026 Sebastiano Barusco - Tutti i diritti riservati"
DB_URL = f"sqlite:///{DB_PATH}"

st.set_page_config(page_title="Osservatorio ACDT", page_icon="⚖️", layout="wide")

# Style istituzionale Bordeaux ACDT
st.markdown("""
    <style>
    .main { background-color: #fcfcfc; }
    h1, h2, h3, h4 { color: #8a1c3d !important; }
    .stButton>button { background-color: #8a1c3d !important; color: white !important; border-radius: 8px; font-weight: bold; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border-left: 5px solid #8a1c3d; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .footer { text-align: center; color: #6c757d; padding: 20px; border-top: 1px solid #dee2e6; margin-top: 50px; font-size: 0.8rem; }
    </style>
    """, unsafe_allow_html=True)

# --- DATABASE ---
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
Base = declarative_base()
class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String); numero = Column(String); massima = Column(Text); autore = Column(String); file_path = Column(String)

Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# --- UTILS AI ---
def formatta_massima_sistematica(m_dati):
    def get_val(keys):
        for k in keys:
            if k in m_dati: return m_dati[k]
            if k.lower() in m_dati: return m_dati[k.lower()]
        return "Dato non rilevato"
    testo = f"**OGGETTO DELLA CAUSA (FATTISPECIE)**:\n{get_val(['oggetto_ampliato', 'oggetto'])}\n\n"
    testo += f"**PRINCIPIO DI DIRITTO**: \n{get_val(['principio', 'principio di diritto'])}\n\n"
    testo += f"**RIFERIMENTI NORMATIVI**: \n{get_val(['norme', 'riferimenti normativi'])}\n\n"
    testo += f"**ESITO DELLA DECISIONE**: \n{get_val(['esito', 'decisione'])}"
    return testo

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = "\n".join([doc[i].get_text() for i in range(min(4, len(doc)))]) + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Sei l'Ufficio del Massimario. Estrai in JSON: organo, numero, massima_dati: {{oggetto_ampliato, principio, norme, esito}}. Testo: {testo[:8000]}"
        chat = client.chat.completions.create(messages=[{"role": "system", "content": "Rispondi in JSON puro."}, {"role": "user", "content": prompt}], model="llama-3.1-8b-instant", temperature=0.1)
        res = re.sub(r'```json\s*|```', '', chat.choices[0].message.content).strip()
        dati = json.loads(re.search(r'\{.*\}', res, re.DOTALL).group())
        return {"organo": dati.get("organo"), "numero": dati.get("numero"), "massima": formatta_massima_sistematica(dati.get("massima_dati", dati))}, None
    except Exception as e: return None, str(e)

def ricerca_ai(domanda, sv):
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    context = "\n".join([f"ID:{s.id} | TESTO:{s.massima[:600]}" for s in sv])
    prompt = f"Identifica tra queste sentenze quelle rilevanti per: {domanda}. Rispondi in JSON: {{'risultati': [{{'id': '...', 'perche': '...'}}]}}. LISTA: {context}"
    try:
        chat = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.1-8b-instant")
        res = re.sub(r'```json\s*|```', '', chat.choices[0].message.content).strip()
        return json.loads(re.search(r'\{.*\}', res, re.DOTALL).group())
    except: return None

# --- ESPORTAZIONE WORD ---
def genera_word(lista):
    doc = Document()
    doc.add_heading('Massimario ACDT', 0).alignment = 1
    for i in lista:
        p = doc.add_paragraph()
        run = p.add_run(f"{i.organo}"); run.bold, run.font.size, run.font.color.rgb = True, Pt(12), RGBColor(138, 28, 61)
        doc.add_paragraph(f"Sentenza n. {i.numero} | Redatto da: {i.autore}").italic = True
        doc.add_paragraph(i.massima.replace("**", "")).alignment = 3
        doc.add_paragraph("-" * 20).alignment = 1
    target = BytesIO(); doc.save(target); return target.getvalue()

# --- INTERFACCIA ---
with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    st.markdown(f"👨‍💻 **Software Author:**\n**{AUTORE_SOFTWARE}**")
    st.caption(COPYRIGHT_NOTE)

tab_home, tab_gest, tab_search, tab_arch = st.tabs(["🏠 Home Page", "📋 Gestione", "🔍 Ricerca AI", "📚 Archivio"])

with tab_home:
    col_l, col_r = st.columns([0.25, 0.75])
    if os.path.exists(LOGO_PATH): col_l.image(LOGO_PATH, use_container_width=True)
    with col_r:
        st.markdown("# Osservatorio Giurisprudenza Tributaria")
        st.markdown("### Associazione Commercialisti Difensori Tributari del Veneto")
    st.markdown("---")
    validati = db.query(Sentenza).filter(Sentenza.stato == "Validato").count()
    total = db.query(Sentenza).count()
    c1, c2, c3 = st.columns(3)
    c1.metric("Analizzate dall'IA", total)
    c2.metric("In Archivio Storico", validati)
    c3.metric("Stato Sistema", "Starter Plan (Persistente)")
    st.markdown("---")
    st.write("#### 🔍 Come Funziona?")
    st.write("1. Carica i PDF nella scheda 'Gestione'.\n2. L'IA estrae i dati e propone una massima sistematica.\n3. Valida le bozze singolarmente o in blocco.\n4. Ricerca i precedenti con linguaggio naturale.")

with tab_gest:
    col_u, col_r = st.columns([0.35, 0.65])
    with col_u:
        st.subheader("📤 Caricamento")
        firma = st.text_input("Firma Redattore", value="Redazione")
        u_files = st.file_uploader("Seleziona PDF", type="pdf", accept_multiple_files=True)
        if st.button("🚀 AVVIA ANALISI SISTEMATICA"):
            if u_files:
                for f in u_files:
                    f_id = str(uuid.uuid4()); path = os.path.join(STORAGE_DIR, f"{f_id}.pdf")
                    with open(path, "wb") as out: out.write(f.getbuffer())
                    with st.spinner(f"Analisi {f.name}..."):
                        res, err = analizza_sentenza(path)
                        if not err:
                            db.add(Sentenza(id=f_id, organo=res["organo"], numero=res["numero"], massima=res["massima"], autore=firma, file_path=path))
                            db.commit()
                st.rerun()
    with col_r:
        st.subheader("✍️ Revisione")
        nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if nuovi:
            if st.button("🚀 PUBBLICA TUTTO ORA"):
                for s in nuovi: s.stato = "Validato"
                db.commit(); st.rerun()
            for s in nuovi:
                with st.expander(f"📝 {s.organo} - n. {s.numero}", expanded=True):
                    o, n = st.text_input("Corte", s.organo, key=f"o{s.id}"), st.text_input("N.", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima", s.massima, height=300, key=f"m{s.id}")
                    if st.button("✅ VALIDA", key=f"p{s.id}"):
                        s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                        db.commit(); st.rerun()
        else: st.info("Nessuna analisi da revisionare.")

with tab_search:
    st.subheader("🔍 Ricerca Semantica")
    domanda = st.text_input("Descrivi un caso o poni un quesito giuridico...")
    if domanda:
        sv = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
        if sv:
            with st.spinner("Consultazione archivio..."):
                r_ia = ricerca_ai(domanda, sv)
                if r_ia and r_ia.get("risultati"):
                    for res in r_ia["risultati"]:
                        s = db.query(Sentenza).filter(Sentenza.id == res["id"]).first()
                        if s:
                            with st.container(border=True):
                                st.markdown(f"#### {s.organo} - n. {s.numero}")
                                st.success(f"RILEVANZA: {res['perche']}")
                                with st.expander("Leggi Massima"): st.write(s.massima)
        else: st.warning("L'archivio è vuoto.")

with tab_arch:
    st.subheader("📚 Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
        out_ex = BytesIO()
        pd.DataFrame([{"Corte": i.organo, "N": i.numero, "Massima": i.massima.replace("**",""), "Autore": i.autore} for i in arch]).to_excel(out_ex, index=False)
        c1.download_button("📊 EXCEL RIEPILOGO", out_ex.getvalue(), "archivio.xlsx", use_container_width=True)
        c2.download_button("📝 WORD REPORT", genera_word(arch), "archivio.docx", use_container_width=True)
        if c3.button("⚠️ RESET", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
        st.divider()
        sk = st.text_input("🔍 Ricerca rapida...")
        for i in arch:
            if sk.lower() in i.massima.lower() or sk.lower() in i.organo.lower():
                with st.container(border=True):
                    ca, cb = st.columns([0.85, 0.15])
                    ca.markdown(f"#### {i.organo}\n**n. {i.numero}** | *Firma: {i.autore}*")
                    ca.write(i.massima)
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as fp:
                            cb.download_button("📄 PDF", fp, f"sentenza_{i.numero}.pdf", key=f"dl_{i.id}")
    else: st.info("Archivio vuoto.")

st.markdown(f"<div class='footer'>{COPYRIGHT_NOTE} | {AUTORE_SOFTWARE}</div>", unsafe_allow_html=True)
db.close()
