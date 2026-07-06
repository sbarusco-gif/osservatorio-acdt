import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- CONFIGURAZIONE ESTETICA E INFO ---
AUTORE_SOFTWARE = "Sebastiano Barusco"
COPYRIGHT_NOTE = "© 2025 Sebastiano Barusco - Tutti i diritti riservati"
DB_URL = "sqlite:///./osservatorio.db"

st.set_page_config(
    page_title="Osservatorio AI - Sebastiano Barusco",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS per un look professionale
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .stExpander { background-color: #ffffff; border-radius: 10px; border: 1px solid #e0e0e0 !important; }
    .footer { position: fixed; left: 0; bottom: 0; width: 100%; text-align: center; color: #6c757d; padding: 10px; background: white; border-top: 1px solid #dee2e6; }
    </style>
    """, unsafe_allow_html=True)

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

# --- FUNZIONI AI (OTTIMIZZATE PER TOKEN) ---
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
        testo = "\n".join([doc[i].get_text() for i in range(min(2, len(doc)))])
        testo += "\n" + doc[-1].get_text()
        doc.close()
        prompt = f"Analizza la sentenza ed estrai in JSON: organo, numero, massima: {{Oggetto, Principio di Diritto, Ragionamento}}. Testo: {testo[:5000]}"
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": "Sei un giurista sintetico. Rispondi in JSON."},
                      {"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.1
        )
        dati = pulisci_json(chat.choices[0].message.content)
        if dati:
            dati["massima_finale"] = formatta_massima_sicura(dati.get("massima"))
            return dati, None
        return None, "Errore formato."
    except Exception as e: return None, str(e)

# --- LOGICA APPLICAZIONE ---
db = SessionLocal()

# Sidebar Stabile
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/law.png", width=80)
    st.title("Menu Principale")
    st.info(f"Benvenuto nell'Osservatorio Digitale gestito da Intelligenza Artificiale.")
    st.markdown("---")
    st.caption(f"👨‍💻 **Autore Software:**\n{AUTORE_SOFTWARE}")
    st.caption(COPYRIGHT_NOTE)

# Tabs Principali
tab_home, tab_gest, tab_arch = st.tabs(["🏠 Home Page", "📋 Gestione Analisi", "📚 Archivio Sentenze"])

# --- TAB HOME ---
with tab_home:
    st.markdown(f"# Benvenuto nell'Osservatorio Giurisprudenza Tributaria")
    st.markdown("### Analisi legale automatizzata con Intelligenza Artificiale")
    
    # Statistiche
    total = db.query(Sentenza).count()
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").count()
    validati = db.query(Sentenza).filter(Sentenza.stato == "Validato").count()
    
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    col_stat1.metric("Sentenze Totali", total)
    col_stat2.metric("Da Revisionare", nuovi, delta_color="inverse")
    col_stat3.metric("Pubblicate in Archivio", validati)
    
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        #### 🔍 Come Funziona?
        1. **Caricamento**: Vai nella scheda **Gestione** e carica i file PDF.
        2. **Analisi IA**: Il software estrae automaticamente l'organo, il numero e redige una massima estesa.
        3. **Validazione**: Tu controlli e modifichi la bozza, poi la pubblichi.
        4. **Consultazione**: Tutti i documenti validati finiscono nell'**Archivio** scaricabile in Excel.
        """)
    with c2:
        st.markdown("#### ⚡️ Tecnologia")
        st.write("Il sistema utilizza modelli linguistici **Llama 3.1** via Groq per garantire velocità e precisione giuridica elevata senza costi di licenza.")

# --- TAB GESTIONE ---
with tab_gest:
    col_l, col_r = st.columns([0.35, 0.65])
    
    with col_l:
        st.subheader("📤 Carica Sentenze")
        firma = st.text_input("Firma Redattore", value="Redazione")
        files = st.file_uploader("Trascina qui i file PDF", type="pdf", accept_multiple_files=True)
        if st.button("🚀 AVVIA ANALISI IA", use_container_width=True):
            if files:
                for f_up in files:
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(f_up.getbuffer())
                    with st.spinner(f"Analisi: {f_up.name}"):
                        res, err = analizza_sentenza(path)
                        if not err:
                            s = Sentenza(id=f_id, organo=res.get("organo"), numero=res.get("numero"),
                                         massima=res.get("massima_finale"), autore=firma, file_path=path)
                            db.add(s); db.commit()
                st.success("Tutte le sentenze sono state analizzate!")
                time.sleep(1); st.rerun()
            else: st.warning("Carica dei file.")

    with col_r:
        st.subheader("✍️ Revisione e Validazione")
        da_validare = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
        if not da_validare:
            st.info("Nessuna sentenza in attesa di revisione.")
        for s in da_validare:
            with st.expander(f"📝 {s.organo} - n. {s.numero}", expanded=True):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima Estesa", s.massima, height=250, key=f"m{s.id}")
                c1, c2 = st.columns(2)
                if c1.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit(); st.rerun()
                if c2.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                    db.delete(s); db.commit(); st.rerun()

# --- TAB ARCHIVIO ---
with tab_arch:
    st.subheader("📚 Archivio Pubblico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    
    if arch:
        # Barra ricerca e export
        col_sch, col_btn = st.columns([0.7, 0.3])
        search = col_sch.text_input("🔍 Cerca per parole chiave nella massima o nell'organo...")
        
        # Filtro ricerca
        arch_filtered = [i for i in arch if search.lower() in i.massima.lower() or search.lower() in i.organo.lower()]
        
        df = pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Autore": i.autore} for i in arch_filtered])
        
        # Export Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.DataFrame([{"Organo": i.organo, "Numero": i.numero, "Massima": i.massima.replace("**", ""), "Autore": i.autore} for i in arch]).to_excel(writer, index=False)
        
        col_btn.download_button("📊 EXPORT EXCEL", data=output.getvalue(), file_name="osservatorio_acdt.xlsx", use_container_width=True)
        if col_btn.button("⚠️ RESET ARCHIVIO", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()

        st.divider()
        for i in arch_filtered:
            with st.container():
                c_a, c_b = st.columns([0.8, 0.2])
                with c_a:
                    st.markdown(f"#### {i.organo}")
                    st.caption(f"Sentenza n. {i.numero} | Redatto da: {i.autore}")
                    st.write(i.massima)
                with c_b:
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as f:
                            st.download_button("📄 PDF", f, file_name=f"{i.numero}.pdf", key=f"dl_{i.id}")
                st.divider()
    else:
        st.info("L'archivio è attualmente vuoto.")

db.close()
