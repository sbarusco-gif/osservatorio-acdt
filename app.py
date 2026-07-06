import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq
from docx import Document # NUOVA LIBRERIA
from docx.shared import Pt, RGBColor

# --- INFO AUTORE ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2025 Sebastiano Barusco - Tutti i diritti riservati"
DB_URL = "sqlite:///./osservatorio.db"
LOGO_PATH = "logo.png"

st.set_page_config(page_title="Osservatorio ACDT", page_icon="⚖️", layout="wide")

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

# --- FUNZIONE GENERAZIONE WORD ---
def genera_word(lista_sentenze):
    doc = Document()
    
    # Titolo del Documento
    titolo = doc.add_heading('Osservatorio Giurisprudenza Tributaria', 0)
    titolo.alignment = 1 # Centrato
    
    doc.add_paragraph(f"Documento generato il {time.strftime('%d/%m/%Y')}\n{COPYRIGHT_NOTE}\n").alignment = 1
    
    for i in lista_sentenze:
        # Intestazione Sentenza
        p = doc.add_paragraph()
        run_org = p.add_run(f"{i.organo}")
        run_org.bold = True
        run_org.font.size = Pt(14)
        run_org.font.color.rgb = RGBColor(138, 28, 61) # Colore Bordeaux ACDT
        
        doc.add_paragraph(f"Sentenza n. {i.numero} | Autore: {i.autore}").italic = True
        
        # Testo della Massima (pulito dai grassetti markdown)
        testo_massima = i.massima.replace("**", "")
        p_massima = doc.add_paragraph(testo_massima)
        p_massima.alignment = 3 # Giustificato
        
        doc.add_paragraph("-" * 40).alignment = 1 # Divisore
        
    # Salvataggio in memoria
    target = BytesIO()
    doc.save(target)
    return target.getvalue()

# --- UTILS IA ---
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
    if not api_key: return None, "Manca API KEY."
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = "\n".join([doc[i].get_text() for i in range(min(3, len(doc)))]) + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Analizza la sentenza ed estrai in JSON: organo, numero, massima: {{Oggetto, Principio di Diritto, Ragionamento}}. Testo: {testo[:6000]}"
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un giurista tributario. Rispondi in JSON."},
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

# --- UI STREAMLIT ---
st.markdown("<style>h1, h2, h3 { color: #8a1c3d !important; }</style>", unsafe_allow_html=True)
db = SessionLocal()

with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    st.markdown("---")
    st.caption(f"🚀 **Software Author:**\n{AUTORE_SOFTWARE}\n\n{COPYRIGHT_NOTE}")

t_home, t_gest, t_arch = st.tabs(["🏠 Home Page", "📋 Gestione Analisi", "📚 Archivio Sentenze"])

# --- HOME ---
with t_home:
    c_logo, c_text = st.columns([0.3, 0.7])
    if os.path.exists(LOGO_PATH): c_logo.image(LOGO_PATH)
    c_text.title("Osservatorio Giurisprudenza Tributaria")
    st.metric("Sentenze in Archivio", db.query(Sentenza).filter(Sentenza.stato == "Validato").count())
    st.info("Benvenuto nell'Osservatorio ACDT. Carica i file PDF per iniziare l'analisi automatica.")

# --- GESTIONE ---
with t_gest:
    c_u, c_r = st.columns([0.3, 0.7])
    with c_u:
        st.subheader("Carica PDF")
        firma = st.text_input("Firma Redattore", value="Redazione")
        files = st.file_uploader("Seleziona", type="pdf", accept_multiple_files=True)
        if st.button("🚀 ANALIZZA"):
            if files:
                for f_up in files:
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(f_up.getbuffer())
                    with st.spinner(f"Analisi: {f_up.name}"):
                        res, err = analizza_sentenza(path)
                        if not err:
                            db.add(Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"),
                                         massima=res.get("massima_finale"), autore=firma, file_path=path))
                            db.commit()
                st.rerun()
    with c_r:
        st.subheader("Revisione")
        for s in db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all():
            with st.expander(f"{s.organo} - {s.numero}"):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
                if st.button("✅ PUBBLICA", key=f"p{s.id}"):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit(); st.rerun()
                if st.button("🗑️ ELIMINA", key=f"d{s.id}"):
                    db.delete(s); db.commit(); st.rerun()

# --- ARCHIVIO ---
with t_arch:
    st.subheader("Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    if arch:
        c1, c2, c3 = st.columns([0.33, 0.33, 0.33])
        
        # Export Excel
        df = pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Massima": i.massima.replace("**",""), "Autore": i.autore} for i in arch])
        out_ex = BytesIO()
        with pd.ExcelWriter(out_ex, engine='openpyxl') as wr: df.to_excel(wr, index=False)
        c1.download_button("📊 EXCEL", out_ex.getvalue(), "riepilogo.xlsx", use_container_width=True)
        
        # Export Word (NUOVO)
        doc_bytes = genera_word(arch)
        c2.download_button("📝 WORD", doc_bytes, "osservatorio.docx", use_container_width=True)
        
        if c3.button("⚠️ RESET", use_container_width=True): db.query(Sentenza).delete(); db.commit(); st.rerun()

        for i in arch:
            with st.container(border=True):
                ca, cb = st.columns([0.8, 0.2])
                ca.markdown(f"#### {i.organo}\n**n. {i.numero}** | *{i.autore}*")
                ca.write(i.massima)
                if os.path.exists(i.file_path):
                    with open(i.file_path, "rb") as fp: cb.download_button("📄 PDF", fp, f"{i.numero}.pdf", key=f"dl_{i.id}")
    else: st.info("Archivio vuoto.")

db.close()
