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

# --- CONFIGURAZIONE ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2026 Sebastiano Barusco - Tutti i diritti riservati" # AGGIORNATO AL 2026
DB_URL = "sqlite:///./osservatorio.db"

# --- FUNZIONE RICERCA LOGO ---
def trova_logo():
    for file in os.listdir('.'):
        if file.lower().startswith('logo') and any(file.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return file
    return None

LOGO_PATH = trova_logo()

st.set_page_config(
    page_title="Osservatorio ACDT - Sebastiano Barusco",
    page_icon="⚖️",
    layout="wide",
)

# Custom CSS con stile Bordeaux ACDT
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
    organo = Column(String); numero = Column(String); massima = Column(String); autore = Column(String); file_path = Column(String)

Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# --- ESPORTAZIONI ---
def genera_word(lista_sentenze):
    doc = Document()
    t = doc.add_heading('Osservatorio Giurisprudenza Tributaria ACDT', 0)
    t.alignment = 1
    for i in lista_sentenze:
        p = doc.add_paragraph()
        run = p.add_run(f"{i.organo}")
        run.bold, run.font.size, run.font.color.rgb = True, Pt(13), RGBColor(138, 28, 61)
        doc.add_paragraph(f"Sentenza n. {i.numero} | Autore: {i.autore}").italic = True
        doc.add_paragraph(i.massima.replace("**", "")).alignment = 3
        doc.add_paragraph("-" * 30).alignment = 1
    target = BytesIO()
    doc.save(target)
    return target.getvalue()

# --- UTILS AI ---
def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Chiave API mancante."
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = "\n".join([doc[i].get_text() for i in range(min(2, len(doc)))]) + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Analizza la sentenza ed estrai in JSON: organo, numero, massima: {{Oggetto, Principio di Diritto, Ragionamento}}. Testo: {testo[:6000]}"
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un giurista tributario. Rispondi in JSON."},
                      {"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant", temperature=0.1
        )
        res = re.sub(r'```json\s*|```', '', chat.choices[0].message.content).strip()
        d = json.loads(re.search(r'\{.*\}', res, re.DOTALL).group())
        m = d.get("massima", {})
        m_str = f"**OGGETTO**:\n{m.get('Oggetto','N/D')}\n\n**PRINCIPIO**:\n{m.get('Principio di Diritto','N/D')}\n\n**RAGIONAMENTO**:\n{m.get('Ragionamento','N/D')}"
        return {"organo": d.get("organo"), "numero": d.get("numero"), "massima": m_str}, None
    except Exception as e: return None, str(e)

# --- SIDEBAR ---
with st.sidebar:
    if LOGO_PATH: st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    st.markdown(f"👨‍💻 **Software Author:**\n**{AUTORE_SOFTWARE}**")
    st.caption(COPYRIGHT_NOTE)

tab_home, tab_gest, tab_arch = st.tabs(["🏠 Home Page", "📋 Gestione Analisi", "📚 Archivio Sentenze"])

# --- HOME ---
with tab_home:
    c_l, c_r = st.columns([0.3, 0.7])
    with c_l: 
        if LOGO_PATH: st.image(LOGO_PATH, use_container_width=True)
    with c_r:
        st.markdown("# Osservatorio Giurisprudenza Tributaria")
        st.markdown("### Intelligenza Artificiale per i Difensori Tributari")
    st.markdown("---")
    v = db.query(Sentenza).filter(Sentenza.stato == "Validato").count()
    t = db.query(Sentenza).count()
    cs1, cs2, cs3 = st.columns(3)
    cs1.metric("Analizzate dall'IA", t)
    cs2.metric("Pubblicate in Archivio", v)
    cs3.metric("Partner Tecnologico", "Groq / Llama 3.1")
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🔍 Funzionamento")
        st.write("1. Carica i PDF nella sezione Gestione.\n2. L'IA estrae i dati e redige la massima.\n3. Pubblica singolarmente o tutto insieme.")
    with c2:
        st.markdown("#### ⚡️ Tecnologia")
        st.write("Piattaforma basata su modelli linguistici avanzati per l'automazione del massimario tributario.")

# --- GESTIONE ---
with tab_gest:
    col_up, col_rev = st.columns([0.35, 0.65])
    with col_up:
        st.subheader("📤 Caricamento")
        firma = st.text_input("Firma Redattore", value="Redazione")
        u_files = st.file_uploader("Seleziona PDF", type="pdf", accept_multiple_files=True)
        if st.button("🚀 AVVIA ANALISI", use_container_width=True):
            if u_files:
                for f in u_files:
                    f_id = str(uuid.uuid4()); path = f"storage/{f_id}.pdf"
                    os.makedirs("storage", exist_ok=True)
                    with open(path, "wb") as out: out.write(f.getbuffer())
                    with st.spinner(f"Analisi {f.name}..."):
                        res, err = analizza_sentenza(path)
                        if not err:
                            db.add(Sentenza(id=f_id, organo=res["organo"], numero=res["numero"], massima=res["massima"], autore=firma, file_path=path))
                            db.commit()
                st.rerun()

    with col_rev:
        st.subheader("✍️ Revisione")
        nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if nuovi:
            if st.button("🚀 PUBBLICA TUTTO (Conferma approvazione di massa)", use_container_width=True):
                for s in nuovi:
                    s.stato = "Validato"
                db.commit()
                st.success(f"Pubblicate {len(nuovi)} sentenze!")
                time.sleep(1); st.rerun()
            
            st.write("---")
            for s in nuovi:
                with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
                    o, n = st.text_input("Corte", s.organo, key=f"o{s.id}"), st.text_input("N.", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima", s.massima, height=250, key=f"m{s.id}")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                        s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                        db.commit(); st.rerun()
                    if c2.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                        db.delete(s); db.commit(); st.rerun()
        else: st.info("Nessuna sentenza in attesa.")

# --- ARCHIVIO ---
with tab_arch:
    st.subheader("📚 Archivio")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
        out_ex = BytesIO()
        with pd.ExcelWriter(out_ex, engine='openpyxl') as wr:
            pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Massima": i.massima.replace("**", ""), "Autore": i.autore} for i in arch]).to_excel(wr, index=False)
        c1.download_button("📊 EXCEL", out_ex.getvalue(), "riepilogo.xlsx", use_container_width=True)
        c2.download_button("📝 WORD", genera_word(arch), "archivio.docx", use_container_width=True)
        if c3.button("⚠️ RESET", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
        
        st.divider()
        search = st.text_input("🔍 Ricerca rapida...")
        for i in arch:
            if search.lower() in i.massima.lower() or search.lower() in i.organo.lower():
                with st.container(border=True):
                    ca, cb = st.columns([0.85, 0.15])
                    with ca:
                        st.markdown(f"#### {i.organo}\n**n. {i.numero}** | *Firma: {i.autore}*")
                        st.write(i.massima)
                    with cb:
                        if os.path.exists(i.file_path):
                            with open(i.file_path, "rb") as fp:
                                st.download_button("📄 PDF", fp, f"sentenza_{i.numero}.pdf", key=f"dl_{i.id}")
    else: st.info("Archivio vuoto.")

st.markdown(f"<div class='footer'>{COPYRIGHT_NOTE} | {AUTORE_SOFTWARE}</div>", unsafe_allow_html=True)
db.close()
