import streamlit as st
import os, uuid, fitz, json, time, re
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- DATABASE ---
DB_URL = "sqlite:///./osservatorio.db"
Base = declarative_base()
class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String); numero = Column(String); massima = Column(String); file_path = Column(String)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def pulisci_json(testo_raw):
    try:
        match = re.search(r'\{.*\}', testo_raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(testo_raw)
    except:
        return None

# --- ANALISI IA AMPLIATA ---
def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca GROQ_API_KEY su Render."
    
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Leggiamo quasi tutto il documento (fino a 10-12 pagine) per catturare la motivazione
        testo_pagine = []
        for i in range(min(12, len(doc))):
            testo_pagine.append(doc[i].get_text())
        
        testo_completo = "\n".join(testo_pagine).strip()
        doc.close()
        
        if len(testo_completo) < 150:
            return None, "Il PDF sembra un'immagine. L'IA non può leggere il testo."

        # PROMPT AMPLIATO PER MASSIME DETTAGLIATE
        prompt = f"""Sei un esperto dell'Ufficio del Massimario della Corte di Cassazione Tributaria. 
        Analizza la sentenza allegata e redigi una MASSIMA GIURIDICA ESTESA e approfondita.
        
        La massima deve essere strutturata seguendo questo schema logico:
        1. OGGETTO: Indica chiaramente l'istituto tributario e la fattispecie trattata.
        2. IL PRINCIPIO DI DIRITTO: Esponi in modo dettagliato il principio astratto stabilito dalla Corte, citando i riferimenti normativi se presenti.
        3. IL RAGIONAMENTO: Spiega brevemente il percorso logico-giuridico seguito dai giudici per arrivare alla decisione.
        
        Sii esaustivo, tecnico e professionale. Evita sintesi eccessive.
        
        Restituisci ESATTAMENTE questo formato JSON:
        {{
          "organo": "nome completo della Corte",
          "numero": "numero e anno della sentenza",
          "massima": "testo esteso della massima articolato in Oggetto, Principio e Ragionamento"
        }}

        Documento da analizzare:
        {testo_completo[:15000]}"""

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sei un giurista di alto livello. Rispondi solo in JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.2, # Leggermente più alta per favorire l'articolazione del testo
            max_tokens=2000 # Permettiamo una risposta lunga
        )
        
        risultato_raw = chat.choices[0].message.content
        dati = pulisci_json(risultato_raw)
        
        if not dati:
            return None, "Errore nella generazione del formato. Riprova."
            
        return dati, None
    except Exception as e:
        return None, f"Errore tecnico: {str(e)}"

# --- UI ---
st.set_page_config(page_title="Osservatorio AI", layout="wide")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria Avanzato")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Upload")
        u_file = st.file_uploader("Carica PDF Sentenza", type="pdf")
        if st.button("🚀 GENERA MASSIMA ESTESA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f: f.write(u_file.getbuffer())
                
                with st.spinner("L'IA sta elaborando una massima approfondita..."):
                    res, err = analizza_sentenza(path)
                    if err:
                        st.error(err)
                    else:
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "Non trovato"), 
                            numero=res.get("numero", "Non trovato"), 
                            massima=res.get("massima", "Errore generazione"), 
                            file_path=path
                        )
                        db.add(s); db.commit()
                        st.success("Massima generata con successo!")
                        time.sleep(1); st.rerun()
            else: st.warning("Carica un file!")

    st.subheader("Revisione Massime IA")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    for s in nuovi:
        with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
            o = st.text_input("Organo", s.organo, key=f"o{s.id}")
            n = st.text_input("Numero", s.numero, key=f"n{s.id}")
            # Aumentata l'altezza della text_area per gestire testi lunghi
            m = st.text_area("Massima Estesa", s.massima, height=450, key=f"m{s.id}")
            c1, c2 = st.columns(2)
            if c1.button("✅ VALIDA E PUBBLICA", key=f"p{s.id}"):
                s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                db.commit(); st.rerun()
            if c2.button("🗑️ CANCELLA", key=f"d{s.id}"):
                db.delete(s); db.commit(); st.rerun()

with t_arch:
    st.subheader("Sentenze Pubblicate")
    if st.button("⚠️ SVUOTA TUTTO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"### {i.organo}")
            st.markdown(f"**Sentenza n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 Scarica PDF Originale", f, file_name=f"{i.numero}.pdf", key=i.id)
db.close()
