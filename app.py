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
COPYRIGHT_NOTE = "© 2025 Sebastiano Barusco - Tutti i diritti riservati"
DB_URL = "sqlite:///./osservatorio.db"
LOGO_PATH = "logo.png"

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
    .stButton>button { background-color: #8a1c3d !important; color: white !important; border-radius: 8px; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border-left: 5px solid #8a1c3d; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .footer { text-align: center; color: #6c757d; padding: 20px; border-top: 1px solid #dee2e6; margin-top: 50px; }
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

# --- FUNZIONE ESPORTAZIONE WORD ---
def genera_word(lista_sentenze):
    doc = Document()
    t = doc.add_heading('Osservatorio Giurisprudenza Tributaria ACDT', 0)
    t.alignment = 1
    doc.add_paragraph(f"Report generato il {time.strftime('%d/%m/%Y')}\n{COPYRIGHT_NOTE}").alignment = 1
    
    for i in lista_sentenze:
        p = doc.add_paragraph()
        run = p.add_run(f"{i.organo}")
        run.bold = True
        run.font.size = Pt(13)
        run.font.color.rgb = RGBColor(138, 28, 61)
        doc.add_paragraph(f"Sentenza n. {i.numero} | Autore: {i.autore}").italic = True
        p_m = doc.add_paragraph(i.massima.replace("**", ""))
        p_m.alignment = 3
        doc.add_paragraph("-" * 30).alignment = 1
    
    target = BytesIO()
    doc.save(target)
    return target.getvalue()

# --- UTILS AI (GROQ) ---
def formatta_massima_sicura(m_input):
    if not m_input: return "Dati non rilevati."
    if isinstance(m_input, dict):
        t = ""
        for k in ["Oggetto", "Principio di Diritto", "Ragionamento"]:
            v = m_input.get(k) or m_input.get(k.lower()) or "N/D"
            t += f"**{k.upper()}**:\n{v}\n\n"
        return t.strip()
    return str(m_input)

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca la chiave API."
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = "\n".join([doc[i].get_text() for i in range(min(2, len(doc)))]) + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Analizza la sentenza ed estrai in JSON: organo, numero, massima: {{Oggetto, Principio di Diritto, Ragionamento}}. Testo: {testo[:6000]}"
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un giurista tributario. Rispondi in JSON."},
                      {"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant", # Più veloce e con limiti token alti
            temperature=0.1
        )
        res = re.sub(r'```json\s*|```', '', chat.choices[0].message.content).strip()
        dati = json.loads(re.search(r'\{.*\}', res, re.DOTALL).group())
        dati["m_finale"] = formatta_massima_sicura(dati.get("massima"))
        return dati, None
    except Exception as e: return None, str(e)

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    st.markdown(f"👨‍💻 **Software Author:**\n**{AUTORE_SOFTWARE}**")
    st.caption(COPYRIGHT_NOTE)

# --- TABS ---
tab_home, tab_gest, tab_arch = st.tabs(["🏠 Home Page", "📋 Gestione Analisi", "📚 Archivio Sentenze"])

# --- TAB HOME ---
with tab_home:
    col_l, col_r = st.columns([0.3, 0.7])
    with col_l:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    with col_r:
        st.markdown("# Osservatorio Giurisprudenza Tributaria")
        st.markdown("### Analisi legale automatizzata con Intelligenza Artificiale")

    st.markdown("---")
    
    # Statistiche dinamiche
    total = db.query(Sentenza).count()
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").count()
    validati = db.query(Sentenza).filter(Sentenza.stato == "Validato").count()
    
    c_s1, c_s2, c_s3 = st.columns(3)
    c_s1.metric("Documenti Processati", total)
    c_s2.metric("In attesa di Revisione", nuovi)
    c_s3.metric("Pubblicati in Archivio", validati)
    
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        #### 🔍 Come Funziona?
        1. **Caricamento**: Vai nella scheda **Gestione** e carica uno o più PDF.
        2. **Analisi IA**: Il sistema (Llama 3.1) estrae i dati e redige la massima estesa.
        3. **Validazione**: Controlla e correggi i dati estratti prima della pubblicazione.
        4. **Export**: Scarica l'intero archivio in formato **Excel** o **Word**.
        """)
    with c2:
        st.markdown("#### ⚡️ Tecnologia")
        st.write("Il sistema utilizza modelli linguistici avanzati per l'estrazione di concetti giuridici, garantendo velocità e precisione.")
        st.info("Piattaforma ottimizzata per l'Associazione Commercialisti Difensori Tributari del Veneto.")

# --- TAB GESTIONE ---
with tab_gest:
    col_up, col_rev = st.columns([0.35, 0.65])
    with col_up:
        st.subheader("📤 Carica PDF")
        firma = st.text_input("Firma Redattore", value="Redazione")
        u_files = st.file_uploader("Seleziona sentenze", type="pdf", accept_multiple_files=True)
        if st.button("🚀 AVVIA ANALISI IA", use_container_width=True):
            if u_files:
                prog = st.progress(0)
                for i, f in enumerate(u_files):
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as out: out.write(f.getbuffer())
                    with st.spinner(f"Analisi: {f.name}"):
                        res, err = analizza_sentenza(path)
                        if not err:
                            s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"),
                                         massima=res.get("m_finale"), autore=firma, file_path=path)
                            db.add(s); db.commit()
                    prog.progress((i + 1) / len(u_files))
                st.success("Analisi completata!"); time.sleep(1); st.rerun()

    with col_rev:
        st.subheader("✍️ Revisione")
        nuovi_list = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if not nuovi_list: st.info("Nessuna sentenza da convalidare.")
        for s in nuovi_list:
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
with tab_arch:
    st.subheader("📚 Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
        
        # Excel Export
        out_ex = BytesIO()
        with pd.ExcelWriter(out_ex, engine='openpyxl') as wr:
            pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Massima": i.massima.replace("**",""), "Autore": i.autore} for i in arch]).to_excel(wr, index=False)
        c1.download_button("📊 EXCEL RIEPILOGO", out_ex.getvalue(), "riepilogo.xlsx", use_container_width=True)
        
        # Word Export
        c2.download_button("📝 WORD MASSIMARIO", genera_word(arch), "osservatorio_acdt.docx", use_container_width=True)
        
        if c3.button("⚠️ SVUOTA ARCHIVIO", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
            
        st.divider()
        search = st.text_input("🔍 Cerca parole chiave nell'archivio...")
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

# --- FOOTER ---
st.markdown(f"<div class='footer'>{COPYRIGHT_NOTE} | {AUTORE_SOFTWARE}</div>", unsafe_allow_html=True)
db.close()
