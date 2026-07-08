import streamlit as st
import os, uuid, fitz, json, time, re, hashlib
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq
from docx import Document
from docx.shared import Pt, RGBColor

# --- CONFIGURAZIONE ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2026 Sebastiano Barusco - Tutti i diritti riservati"
ADMIN_USER = "admin" # Username Amministratore
ADMIN_PASS = "acdt2026" # Password Amministratore (CAMBIALA)

DB_URL_DIR = "/var/lib/data" if os.environ.get("RENDER") else "."
DB_PATH = os.path.join(DB_URL_DIR, "osservatorio_v4.db")
STORAGE_DIR = os.path.join(DB_URL_DIR, "sentenze_pdf")
LOGO_PATH = "logo.png"

if not os.path.exists(STORAGE_DIR): os.makedirs(STORAGE_DIR, exist_ok=True)

st.set_page_config(page_title="Osservatorio ACDT", page_icon="⚖️", layout="wide")

# --- DATABASE ---
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    password = Column(String)
    role = Column(String) # 'Redattore' o 'Consultatore'
    is_approved = Column(Boolean, default=False)

class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String); numero = Column(String); massima = Column(Text)
    autore = Column(String); file_path = Column(String)

Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# --- SICUREZZA ---
def hash_pw(password): return hashlib.sha256(str.encode(password)).hexdigest()

# --- STYLE BORDEAUX ---
st.markdown("""
    <style>
    .main { background-color: #fcfcfc; }
    h1, h2, h3, h4 { color: #8a1c3d !important; }
    .stButton>button { background-color: #8a1c3d !important; color: white !important; border-radius: 8px; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border-left: 5px solid #8a1c3d; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .footer { text-align: center; color: #6c757d; padding: 20px; border-top: 1px solid #eee; margin-top: 50px; font-size: 0.8rem; }
    </style>
    """, unsafe_allow_html=True)

# --- SESSIONE ---
if 'auth' not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = ""
    st.session_state.role = ""
    st.session_state.approved = False

# --- LOGIN / REGISTRAZIONE ---
if not st.session_state.auth:
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH)
        st.markdown("<h2 style='text-align:center;'>Osservatorio Giurisprudenza</h2>", unsafe_allow_html=True)
        mode = st.radio("Scegli", ["Accedi", "Registrati"], horizontal=True)
        
        with st.form("auth"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            r = "Consultatore"
            if mode == "Registrati":
                r = st.selectbox("Ruolo desiderato", ["Consultatore", "Redattore"])
            
            if st.form_submit_button("Conferma"):
                if mode == "Registrati":
                    if db.query(User).filter(User.username == u).first():
                        st.error("Username esistente")
                    else:
                        # L'admin è sempre approvato, i consultatori pure, i redattori no
                        approved = True if r == "Consultatore" or u == ADMIN_USER else False
                        db.add(User(username=u, password=hash_pw(p), role=r, is_approved=approved))
                        db.commit()
                        st.success("Registrato! Se hai scelto 'Redattore', attendi l'approvazione dell'amministratore.")
                else:
                    user_db = db.query(User).filter(User.username == u).first()
                    if u == ADMIN_USER and p == ADMIN_PASS:
                        st.session_state.auth, st.session_state.user, st.session_state.role, st.session_state.approved = True, u, "Admin", True
                        st.rerun()
                    elif user_db and user_db.password == hash_pw(p):
                        st.session_state.auth, st.session_state.user, st.session_state.role, st.session_state.approved = True, u, user_db.role, user_db.is_approved
                        st.rerun()
                    else: st.error("Credenziali errate")
    st.stop()

# --- LOGICA AI (SISTEMATICA) ---
def formatta_massima(m_dati):
    def g(keys):
        for k in keys:
            if k in m_dati: return m_dati[k]
        return "N/D"
    return f"**OGGETTO**: {g(['oggetto_ampliato', 'oggetto'])}\n\n**PRINCIPIO**: {g(['principio'])}\n\n**NORME**: {g(['norme'])}\n\n**ESITO**: {g(['esito'])}"

def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        testo = doc[0].get_text() + "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Analizza la sentenza ed estrai in JSON: organo, numero, massima_dati: {{oggetto_ampliato, principio, norme, esito}}. Testo: {testo[:7000]}"
        chat = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.1-8b-instant", response_format={"type": "json_object"})
        dati = json.loads(chat.choices[0].message.content)
        return {"o": dati.get("organo"), "n": dati.get("numero"), "m": formatta_massima(dati.get("massima_dati", {}))}, None
    except Exception as e: return None, str(e)

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH)
    st.write(f"👤 Utente: **{st.session_state.user}**")
    st.write(f"🛡️ Ruolo: **{st.session_state.role}**")
    if not st.session_state.approved:
        st.warning("⚠️ Accesso limitato: in attesa di approvazione")
    if st.button("Logout"):
        st.session_state.auth = False
        st.rerun()
    st.markdown("---")
    st.caption(f"{AUTORE_SOFTWARE} | {COPYRIGHT_NOTE}")

# --- TABS DINAMICI ---
tabs_list = ["🏠 Home"]
if st.session_state.role == "Admin": tabs_list.append("🛡️ Amministrazione")
if st.session_state.role in ["Redattore", "Admin"] and st.session_state.approved:
    tabs_list.append("📋 Gestione Analisi")
tabs_list.extend(["🔍 Ricerca AI", "📚 Archivio"])
tabs = st.tabs(tabs_list)

# --- HOME ---
with tabs[0]:
    st.markdown(f"# Benvenuto nell'Osservatorio ACDT")
    c1, c2, c3 = st.columns(3)
    c1.metric("Sentenze Validate", db.query(Sentenza).filter(Sentenza.stato == "Validato").count())
    c2.metric("Utenti", db.query(User).count())
    c3.metric("Il tuo Stato", "Attivo" if st.session_state.approved else "Sola Lettura")

# --- AMMINISTRAZIONE (Solo Admin) ---
if st.session_state.role == "Admin":
    with tabs[1]:
        st.subheader("Utenti in attesa di approvazione")
        pending = db.query(User).filter(User.role == "Redattore", User.is_approved == False).all()
        if pending:
            for u in pending:
                col_u, col_b = st.columns([0.7, 0.3])
                col_u.write(f"Account: **{u.username}** richiede ruolo Redattore")
                if col_b.button("APPROVA", key=f"app_{u.username}"):
                    u.is_approved = True
                    db.commit()
                    st.success(f"Utente {u.username} approvato!")
                    st.rerun()
        else: st.info("Nessuna richiesta pendente.")

# --- GESTIONE (Solo Redattori Approvati o Admin) ---
if "📋 Gestione Analisi" in tabs_list:
    idx = tabs_list.index("📋 Gestione Analisi")
    with tabs[idx]:
        col1, col2 = st.columns([0.4, 0.6])
        with col1:
            u_files = st.file_uploader("Carica PDF", type="pdf", accept_multiple_files=True)
            if st.button("AVVIA IA"):
                if u_files:
                    for f in u_files:
                        f_id = str(uuid.uuid4()); path = os.path.join(STORAGE_DIR, f"{f_id}.pdf")
                        with open(path, "wb") as out: out.write(f.getbuffer())
                        res, err = analizza_sentenza(path)
                        if not err:
                            db.add(Sentenza(id=f_id, organo=res["o"], numero=res["n"], massima=res["m"], autore=st.session_state.user, file_path=path))
                            db.commit()
                    st.rerun()
        with col2:
            nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
            for s in nuovi:
                with st.expander(f"📝 {s.organo}"):
                    o, n = st.text_input("Corte", s.organo, key=f"o{s.id}"), st.text_input("Numero", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima", s.massima, height=200, key=f"m{s.id}")
                    if st.button("PUBBLICA", key=f"p{s.id}"):
                        s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                        db.commit(); st.rerun()

# --- ARCHIVIO ---
idx_arch = tabs_list.index("📚 Archivio")
with tabs[idx_arch]:
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"#### {i.organo} - {i.numero}")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as fp: st.download_button("📂 PDF", fp, f"{i.numero}.pdf", key=f"d{i.id}")

db.close()
