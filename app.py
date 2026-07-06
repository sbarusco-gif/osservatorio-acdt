import streamlit as st
import os, uuid, fitz, json, time, re
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from groq import Groq

# --- DATABASE CONFIG ---
DB_URL = "sqlite:///./osservatorio.db"
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

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# --- UTILS DI FORMATTAZIONE ---
def formatta_massima_sicura(m_input):
    """Evita il valore 'None' e formatta bene il testo"""
    if not m_input:
        return "ATTENZIONE: Massima non generata correttamente dall'IA. Revisionare manualmente."
    
    if isinstance(m_input, dict):
        testo = ""
        # Cerchiamo le chiavi classiche, altrimenti prendiamo tutto
        chiavi = ["Oggetto", "Principio di Diritto", "Ragionamento"]
        for k in chiavi:
            valore = m_input.get(k) or m_input.get(k.lower()) or "Dato non rilevato"
            testo += f"**{k.upper()}**:\n{valore}\n\n"
        return testo.strip()
    
    return str(m_input)

def pulisci_json(testo_raw):
    """Estrae il JSON in modo ultra-robusto"""
    try:
        # Pulizia da Markdown e spazi
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
    if not api_key: return None, "Manca la chiave API nelle impostazioni di Render."
    
    client = Groq(api_key=api_key)
    try:
        doc = fitz.open(file_path)
        # Leggiamo più testo possibile (prime 8 pagine e ultima)
        pagine = [doc[i].get_text() for i in range(min(8, len(doc)))]
        if len(doc) > 8: pagine.append(doc[-1].get_text())
        testo_estratto = "\n".join(pagine).strip()
        doc.close()
        
        if len(testo_estratto) < 150:
            return None, "Il PDF sembra non contenere testo leggibile."

        prompt = f"""Analizza questa sentenza tributaria e redigi una MASSIMA GIURIDICA ESTESA.
        Rispondi ESCLUSIVAMENTE con un JSON puro avente queste chiavi:
        - "organo": nome della corte
        - "numero": numero/anno sentenza
        - "massima": {{
            "Oggetto": "...",
            "Principio di Diritto": "...",
            "Ragionamento": "..."
          }}

        SENTENZA DA ANALIZZARE:
        {testo_estratto[:15000]}"""

        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sei un esperto di Massimario. Rispondi solo in JSON. Se un dato manca scrivi 'N/D'."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=3000
        )
        
        raw_content = chat.choices[0].message.content
        dati = pulisci_json(raw_content)
        
        if not dati:
            return None, "L'IA ha risposto in un formato non valido."
            
        # Formattiamo la massima prima di restituirla
        dati["massima_finale"] = formatta_massima_sicura(dati.get("massima"))
        return dati, None
        
    except Exception as e:
        return None, f"Errore tecnico: {str(e)}"

# --- INTERFACCIA STREAMLIT ---
st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

db = SessionLocal()
t_gest, t_arch = st.tabs(["📋 Gestione e Revisione", "📚 Archivio Storico"])

with t_gest:
    with st.sidebar:
        st.header("Caricamento")
        autore_default = st.text_input("Firma Autore", value="Redazione")
        u_files = st.file_uploader("Seleziona uno o più PDF", type="pdf", accept_multiple_files=True)
        
        if st.button("🚀 ELABORA SENTENZE"):
            if u_files:
                progress = st.progress(0)
                for index, u_file in enumerate(u_files):
                    f_id = str(uuid.uuid4())
                    os.makedirs("storage", exist_ok=True)
                    path = f"storage/{f_id}.pdf"
                    with open(path, "wb") as f: f.write(u_file.getbuffer())
                    
                    res, err = analizza_sentenza(path)
                    if not err:
                        s = Sentenza(
                            id=f_id, 
                            organo=res.get("organo", "Non rilevato"), 
                            numero=res.get("numero", "Non rilevato"), 
                            massima=res.get("massima_finale"), 
                            autore=autore_default,
                            file_path=path
                        )
                        db.add(s); db.commit()
                    else:
                        st.sidebar.error(f"Errore su {u_file.name}: {err}")
                    
                    progress.progress((index + 1) / len(u_files))
                st.success("Operazione completata!"); time.sleep(1); st.rerun()
            else: st.warning("Carica almeno un file.")

    st.subheader("Massime da Revisionare")
    nuovi = db.query(Sentenza).filter(Sentenza.stato == "Nuovo").all()
    if nuovi:
        for s in nuovi:
            with st.expander(f"📝 {s.organo} - {s.numero} (Firma: {s.autore})", expanded=False):
                c1, c2 = st.columns([0.7, 0.3])
                with c1:
                    o = st.text_input("Organo", s.organo, key=f"o{s.id}")
                    n = st.text_input("Numero", s.numero, key=f"n{s.id}")
                    m = st.text_area("Massima Estesa", s.massima, height=350, key=f"m{s.id}")
                with c2:
                    aut = st.text_input("Modifica Firma", s.autore, key=f"a{s.id}")
                    st.write("---")
                    if st.button("✅ PUBBLICA", key=f"p{s.id}", use_container_width=True):
                        s.organo, s.numero, s.massima, s.autore, s.stato = o, n, m, aut, "Validato"
                        db.commit(); st.rerun()
                    if st.button("🗑️ ELIMINA", key=f"d{s.id}", use_container_width=True):
                        db.delete(s); db.commit(); st.rerun()
    else:
        st.info("Nessuna sentenza in attesa di revisione.")

with t_arch:
    st.subheader("Archivio Storico")
    arch = db.query(Sentenza).filter(Sentenza.stato == "Validato").all()
    
    if arch:
        c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
        
        # EXPORT EXCEL
        df = pd.DataFrame([{
            "Organo": i.organo,
            "Sentenza": i.numero,
            "Massima": i.massima.replace("**", ""),
            "Autore": i.autore
        } for i in arch])
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Archivio')
        
        c1.download_button("📊 SCARICA EXCEL", data=output.getvalue(), file_name="osservatorio_sentenze.xlsx", use_container_width=True)
        
        if c3.button("⚠️ SVUOTA ARCHIVIO", use_container_width=True):
            db.query(Sentenza).delete(); db.commit(); st.rerun()
        
        st.divider()

        for i in arch:
            with st.container(border=True):
                col_a, col_b = st.columns([0.8, 0.2])
                with col_a:
                    st.markdown(f"### {i.organo}")
                    st.markdown(f"**Sentenza n. {i.numero}** | *Autore: {i.autore}*")
                    st.write(i.massima)
                with col_b:
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as f:
                            st.download_button("📂 PDF", f, file_name=f"{i.numero}.pdf", key=f"dl_{i.id}")
    else:
        st.info("Archivio vuoto.")

db.close()
                    if os.path.exists(i.file_path):
                        with open(i.file_path, "rb") as f:
                            st.download_button("📂 PDF", f, file_name=f"{i.numero}.pdf", key=f"dl_{i.id}")
    else:
        st.info("Archivio vuoto.")

db.close()
