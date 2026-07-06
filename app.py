import streamlit as st
import os, uuid, fitz, json, time, re
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- CONFIGURAZIONE DATABASE ---
DB_URL = "sqlite:///./osservatorio.db"
Base = declarative_base()

class Sentenza(Base):
    __tablename__ = "sentenze"
    id = Column(String, primary_key=True)
    stato = Column(String, default="Nuovo") 
    organo = Column(String)
    numero = Column(String)
    massima = Column(String) # Qui salveremo il testo convertito
    file_path = Column(String)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# --- UTILS ---
def formatta_massima(m_input):
    """Converte un eventuale dizionario IA in una stringa leggibile per il DB"""
    if isinstance(m_input, dict):
        testo = ""
        for chiave, valore in m_input.items():
            testo += f"{chiave.upper()}:\n{valore}\n\n"
        return testo.strip()
    return str(m_input)

def pulisci_json(testo_raw):
    """Estrae il JSON in modo sicuro"""
    try:
        testo_pulito = re.sub(r'```json\s*|```', '', testo_raw).strip()
        match = re.search(r'\{.*\}', testo_pulito, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(testo_pulito)
    except:
        return None

# --- ANALISI IA ---
def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca GROQ_API_KEY su Render."
    
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Leggiamo le prime 5 pagine e l'ultima (per i dati e il PQM)
        pagine = [doc[i].get_text() for i in range(min(5, len(doc)))]
        if len(doc) > 5: pagine.append(doc[-1].get_text())
        testo_estratto = "\n".join(pagine).strip()
        doc.close()
        
        if len(testo_estratto) < 200:
            return None, "PDF non leggibile (scansione immagine?)."

        prompt = f"""Analizza questa sentenza tributaria e redigi una MASSIMA GIURIDICA ESTESA.
        Restituisci ESCLUSIVAMENTE un oggetto JSON con:
        - "organo": nome della corte
        - "numero": numero/anno
        - "massima": {{
            "Oggetto": "...",
            "Principio di Diritto": "...",
            "Ragionamento": "..."
          }}

        DOCUMENTO:
        {testo_estratto[:12000]}"""

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sei un esperto giurista. Rispondi solo in JSON puro."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=3000
        )
        
        dati = pulisci_json(chat.choices[0].message.content)
        if not dati: return None, "Errore nel formato dei dati generati."
        
        # TRASFORMAZIONE CRUCIALE: Convertiamo la massima (dict) in stringa per SQLite
        dati["massima_formattata"] = formatta_massima(dati.get("massima", "N/D"))
        
        return dati, None
    except Exception as e:
        return None, f"Errore tecnico: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="Osservatorio AI", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Caricamento e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Carica Sentenza")
        u_file = st.file_uploader("Trascina il PDF qui", type="pdf")
        if st.button("🚀 GENERA MASSIMA ESTESA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f: f.write(u_file.getbuffer())
                
                with st.spinner("Analisi professionale con Llama 3.3 in corso..."):
                    res, err = analizza_sentenza(path)
                    if err:
                        st.error(err)
                    else:
                        # Qui usiamo la massima formattata come stringa
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "N/D"), 
                            numero=res.get("numero", "N/D"), 
                            massima=res.get("massima_formattata", "N/D"), 
                            file_path=path
                        )
                        try:
                            db.add(s)
                            db.commit()
                            st.success("Analisi completata!")
                            time.sleep(1); st.rerun()
                        except Exception as db_err:
                            st.error(f"Errore salvataggio DB: {db_err}")
            else: st.warning("Carica un file!")

    st.subheader("Massime da Revisionare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"📝 {s.organo} - {s.numero}", expanded=True):
                o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                m = st.text_area("Massima Estesa", s.massima, height=400, key=f"m{s.id}")
                c1, c2 = st.columns(2)
                if c1.button("✅ PUBBLICA", key=f"p{s.id}"):
                    s.organo, s.numero, s.massima, s.stato = o, n, m, "Validato"
                    db.commit(); st.rerun()
                if c2.button("🗑️ ELIMINA", key=f"d{s.id}"):
                    db.delete(s); db.commit(); st.rerun()
    else: st.info("Nessuna sentenza in attesa di revisione.")

with t_arch:
    st.subheader("Sentenze Pubblicate")
    if st.button("⚠️ SVUOTA ARCHIVIO"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"### {i.organo}")
            st.markdown(f"**Sentenza n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 Scarica PDF", f, file_name=f"{i.numero}.pdf", key=i.id)

db.close()
