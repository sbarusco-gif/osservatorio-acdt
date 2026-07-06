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
COPYRIGHT_NOTE = "© 2026 Sebastiano Barusco - Tutti i diritti riservati"
DB_URL = "sqlite:///./osservatorio.db"

def trova_logo():
    for file in os.listdir('.'):
        if file.lower().startswith('logo') and any(file.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return file
    return None

LOGO_PATH = trova_logo()

st.set_page_config(page_title="Osservatorio ACDT", page_icon="⚖️", layout="wide")

# Style istituzionale
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

# --- UTILS AI ---
def formatta_massima_professionale(d):
    m = d.get("massima", {})
    testo = f"**RUBRICA/OGGETTO**:\n{m.get('Oggetto', 'N/D')}\n\n"
    testo += f"**MASSIMA/PRINCIPIO DI DIRITTO**:\n{m.get('Principio', 'N/D')}\n\n"
    testo += f"**IL CASO/FATTISPECIE**:\n{m.get('Fattispecie', 'N/D')}"
    return testo

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca API KEY."
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = "\n".join([doc[i].get_text() for i in range(min(4, len(doc)))]) + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"""Sei un Magistrato addetto all'Ufficio del Massimario. Analizza la sentenza tributaria ed estrai in JSON: "organo", "numero", "massima": {{"Oggetto": "...", "Principio": "...", "Fattispecie": "..."}}. 
        Testo Sentenza: {testo[:8000]}"""
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Rispondi solo in JSON."}, {"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant", temperature=0.0
        )
        res_raw = re.sub(r'```json\s*|```', '', chat.choices[0].message.content).strip()
        dati = json.loads(re.search(r'\{.*\}', res_raw, re.DOTALL).group())
        return {"organo": dati.get("organo"), "numero": dati.get("numero"), "massima": formatta_massima_professionale(dati)}, None
    except Exception as e: return None, str(e)

# --- ESPORTAZIONE WORD ---
def genera_word(lista_sentenze):
    doc = Document()
    t = doc.add_heading('Massimario Giurisprudenza Tributaria ACDT', 0)
    t.alignment = 1
    for i in lista_sentenze:
        p = doc.add_paragraph()
        run = p.add_run(f"{i.organo}")
        run.bold, run.font.size, run.font.color.rgb = True, Pt(12), RGBColor(138, 28, 61)
        doc.add_paragraph(f"Sentenza n. {i.numero} | Autore: {i.autore}").italic = True
        p_m = doc.add_paragraph(i.massima.replace("**", ""))
        p_m.alignment = 3 
        doc.add_paragraph("-" * 30).alignment = 1
    target = BytesIO(); doc.save(target)
    return target.getvalue()

# --- UI ---
with st.sidebar:
    if LOGO_PATH: st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    st.markdown(f"👨‍💻 **Software Author:**\n**{AUTORE_SOFTWARE}**")
    st.caption(COPYRIGHT_NOTE)

tab_home, tab_gest, tab_arch = st.tabs(["🏠 Home Page", "📋 Gestione Analisi", "📚 Archivio Sentenze"])

# --- TAB HOME ---
with tab_home:
    col_l, col_r = st.columns([0.3, 0.7])
    with col_l: 
        if LOGO_PATH: st.image(LOGO_PATH, use_container_width=True)
    with col_r:
        st.markdown("# Osservatorio Giurisprudenza Tributaria")
        st.markdown("### Associazione Commercialisti Difensori Tributari del Veneto")

    st.markdown("---")
    v = db.query(Sentenza).filter(Sentenza.stato == "Validato").count()
    t = db.query(Sentenza).count()
    cs1, cs2 = st.columns(2) # Ridotto a 2 colonne
    cs1.metric("Sentenze Totali Processate", t)
    cs2.metric("Sentenze Pubblicate in Archivio", v)
    
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🔍 Metodologia")
        st.write("Il sistema isola il principio di diritto applicato dai giudici tributari, distinguendo la rubrica dall'analisi del caso concreto.")
    with c2:
        st.markdown("#### 📄 Output")
        st.write("Le analisi possono essere esportate in formato Microsoft Word o Excel per la creazione di report professionali o banche dati locali.")

# --- TAB GESTIONE ---
with tab_gest:
    col_up, col_rev = st.columns([0.35, 0.65])
    with col_up:
        st.subheader("📤 Caricamento")
        firma = st.text_input("Firma Redattore", value="Redazione")
        u_files = st.file_uploader("Seleziona i PDF", type="pdf", accept_multiple_files=True)
        if st.button("🚀 AVVIA ELABORAZIONE", use_container_width=True):
            if u_files:
                for f in u_files:
                    f_id = str(uuid.uuid4()); path = f"storage/{f_id}.pdf"
                    os.makedirs("storage", exist_ok=True)
                    with open(path, "wb") as out: out.write(f.getbuffer())
                    with st.spinner(f"Analisi: {f.name}..."):
                        res, err = analizza_sentenza(path)
                        if not err:
                            db.add(Sentenza(id=f_id, organo=res["organo"], numero=res["numero"], massima=res["massima"], autore=firma, file_path=path))
                            db.commit()
                st.rerun()

    with col_rev:
        st.subheader("✍️ Revisione")
        nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if nuovi:
            if st.button("🚀 PUBBLICA TUTTI I DOCUMENTI", use_container_width=True):
                for s in nuovi: s.stato = "Validato"
                db.commit(); st.rerun()
            for s in nuovi:
                with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
                    o, n = st.text_input("Corte", s.organo, key=f"o{s.id}"), st.text_input("N.", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima", s.massima, height=350, key=f"m{s.id}")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ VALIDA", key=f"p{s.id}", use_container_width=True):
                        s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                        db.commit(); st.rerun()
                    if c2.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                        db.delete(s); db.commit(); st.rerun()
        else: st.info("Nessuna analisi in attesa.")

# --- TAB ARCHIVIO ---
with tab_arch:
    st.subheader("📚 Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
        out_ex = BytesIO()
        with pd.ExcelWriter(out_ex, engine='openpyxl') as wr:
            pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Massima": i.massima.replace("**",""), "Autore": i.autore} for i in arch]).to_excel(wr, index=False)
        c1.download_button("📊 EXCEL RIEPILOGO", out_ex.getvalue(), "archivio_acdt.xlsx", use_container_width=True)
        c2.download_button("📝 WORD REPORT", genera_word(arch), "report_acdt.docx", use_container_width=True)
        if c3.button("⚠️ RESET", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
        
        st.divider()
        search = st.text_input("🔍 Ricerca rapida nell'archivio...")
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
    else: st.info("L'archivio è vuoto.")

st.markdown(f"<div class='footer'>{COPYRIGHT_NOTE} | {AUTORE_SOFTWARE}</div>", unsafe_allow_html=True)
db.close()
