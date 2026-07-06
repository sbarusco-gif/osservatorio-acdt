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

# --- PULIZIA JSON AVANZATA ---
def pulisci_json(testo_raw):
    """Estrae il JSON cercando di ignorare testo spurio o interruzioni"""
    try:
        # Rimuove eventuali blocchi di codice markdown ```json ... ```
        testo_pulito = re.sub(r'```json\s*|```', '', testo_raw).strip()
        # Cerca la prima parentesi graffa e l'ultima
        inizio = testo_pulito.find('{')
        fine = testo_pulito.rfind('}')
        if inizio != -1 and fine != -1:
            testo_json = testo_pulito[inizio:fine+1]
            return json.loads(testo_json)
        return json.loads(testo_pulito)
    except Exception as e:
        print(f"Errore parsing JSON: {e}")
        return None

# --- ANALISI IA ROBUSTA ---
def analizza_sentenza(file_path):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return None, "Manca la chiave API su Render."
    
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Leggiamo le prime 6 pagine e le ultime 2 (cuore della sentenza)
        pagine = []
        for i in range(min(6, len(doc))):
            pagine.append(doc[i].get_text())
        if len(doc) > 6:
            pagine.append(doc[-1].get_text())
        
        testo_estratto = "\n".join(pagine).strip()
        doc.close()
        
        if len(testo_estratto) < 200:
            return None, "PDF non leggibile (scansione immagine?)."

        # Prompt ultra-chiaro per evitare errori di formato
        prompt = f"""Analizza questa sentenza tributaria e redigi una MASSIMA GIURIDICA ESTESA.
        Dovrai restituire ESCLUSIVAMENTE un oggetto JSON con le chiavi "organo", "numero", "massima".
        
        Nella chiave "massima" includi:
        1. OGGETTO (La materia trattata)
        2. IL PRINCIPIO DI DIRITTO (La regola stabilita)
        3. IL RAGIONAMENTO (Sintesi della motivazione)
        
        REGOLE PER IL JSON:
        - Non usare virgolette all'interno dei testi, usa l'apostrofo.
        - Non andare a capo all'interno delle stringhe, usa lo spazio.
        - Rispondi solo con il JSON.

        TESTO SENTENZA:
        {testo_estratto[:12000]}"""

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sei un massimario della Corte di Cassazione. Rispondi solo in JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0, # Riduce la creatività per evitare errori di formato
            max_tokens=3000
        )
        
        risultato_raw = chat.choices[0].message.content
        dati = pulisci_json(risultato_raw)
        
        if not dati:
            return None, f"L'IA ha risposto in modo errato. Prova con un file più breve o riprova tra un istante."
            
        return dati, None
    except Exception as e:
        return None, f"Errore tecnico: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="Osservatorio AI", layout="wide")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione", "📚 Archivio"])

with t_gest:
    with st.sidebar:
        st.header("Carica Documento")
        u_file = st.file_uploader("Seleziona PDF", type="pdf")
        if st.button("🚀 GENERA MASSIMA"):
            if u_file:
                f_id = str(uuid.uuid4())
                os.makedirs("storage", exist_ok=True)
                path = f"storage/{f_id}.pdf"
                with open(path, "wb") as f: f.write(u_file.getbuffer())
                
                with st.spinner("L'IA sta lavorando..."):
                    res, err = analizza_sentenza(path)
                    if err:
                        st.error(err)
                    else:
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "N/D"), 
                            numero=res.get("numero", "N/D"), 
                            massima=res.get("massima", "N/D"), 
                            file_path=path
                        )
                        db.add(s); db.commit()
                        st.success("Completato!")
                        time.sleep(1); st.rerun()
            else: st.warning("Seleziona un file.")

    st.subheader("Fascicoli in Revisione")
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
                if c2.button("🗑️ CANCELLA", key=f"d{s.id}"):
                    db.delete(s); db.commit(); st.rerun()
    else: st.info("Nessuna sentenza in attesa.")

with t_arch:
    st.subheader("Archivio Storico")
    if st.button("⚠️ SVUOTA"):
        db.query(Sentenza).delete(); db.commit(); st.rerun()
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    for i in arch:
        with st.container(border=True):
            st.markdown(f"**{i.organo} - n. {i.numero}**")
            st.write(i.massima)
            if os.path.exists(i.file_path):
                with open(i.file_path, "rb") as f:
                    st.download_button("📂 PDF", f, file_name=f"{i.numero}.pdf", key=i.id)
db.close()
