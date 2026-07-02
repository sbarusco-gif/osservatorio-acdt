import os
import uuid
import shutil
import json
import fitz  # PyMuPDF
import openai
from typing import List
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import models, schemas, database

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - Massimario PRO")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# --- MOTORE DI ANALISI GIURIDICA ---
def analizza_sentenza_tecnica(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    
    try:
        # 1. LETTURA PDF
        doc = fitz.open(file_path)
        testo_estratto = ""
        # Leggiamo le prime 10 pagine per avere una visione completa
        for pagina in doc.pages(0, min(10, len(doc))):
            testo_estratto += pagina.get_text("text")
        doc.close()

        # 2. CONTROLLO PDF (È UN'IMMAGINE?)
        if len(testo_estratto.strip()) < 100:
            raise ValueError("DOCUMENTO NON LEGGIBILE: Il PDF è una scansione o una foto. L'IA non può leggere il testo se non è un PDF testuale.")

        if not api_key:
            raise ValueError("CONFIGURAZIONE MANCANTE: Manca la OPENAI_API_KEY nelle impostazioni di Render.")

        # 3. CHIAMATA A OPENAI CON PROMPT GIURIDICO
        client = openai.OpenAI(api_key=api_key)
        
        prompt_sistema = """
        Sei un Magistrato Tributarista dell'Ufficio del Massimario. 
        Analizza la sentenza ed estrai i dati ESCLUSIVAMENTE in formato JSON.
        
        REGOLE PER LA MASSIMA TECNICA:
        - Deve essere un principio di diritto ASTRATTO e UNIVERSALE.
        - Inizia con 'In tema di [Argomento]...'.
        - NON usare nomi di persone o società (usa: 'il contribuente', 'l'Amministrazione').
        - NON copiare frasi della sentenza, devi sintetizzare la RATIO DECIDENDI.
        """
        
        prompt_utente = f"""
        Estrai organo, numero sentenza, data deposito e massima tecnica da questo testo:
        
        {testo_estratto[:15000]}
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_utente}
            ],
            response_format={ "type": "json_object" }
        )
        
        dati = json.loads(response.choices[0].message.content)

        # 4. SALVATAGGIO DATI
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati.get("organo", "Non rilevato"),
            numero_sentenza_ai=dati.get("numero", "N/D"),
            massima_ai=dati.get("massima", "Errore nella generazione della massima"),
            note_riservate=f"Data: {dati.get('data', 'N/D')} | Norme: {dati.get('norme', 'N/D')}"
        )
        db.add(nuova_scheda)
        
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f: f.stato = models.StatoFascicolo.Da_validare
        
        db.commit()

    except Exception as e:
        # SALVATAGGIO ERRORE (Così lo vedi nella Dashboard)
        db.add(models.Scheda(
            id_fascicolo=id_fascicolo, 
            organo_ai="ERRORE SISTEMA", 
            massima_ai=f"L'analisi è fallita. Motivo: {str(e)}"
        ))
        db.commit()
    finally:
        db.close()

# --- ENDPOINTS ---

@app.post("/v1/fascicoli/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b: shutil.copyfileobj(file.file, b)
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n); db.commit(); db.refresh(n)
    background_tasks.add_task(analizza_sentenza_tecnica, n.id, f_path)
    return n

@app.get("/v1/fascicoli")
def list_f(db: Session = Depends(database.get_db)): return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: uuid.UUID, db: Session = Depends(database.get_db)): 
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente, s.numero_sentenza_corrente, s.massima_corrente = payload.organo, payload.numero, payload.massima
        f.stato = models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    data = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    return [{"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente} for s in data]

@app.get("/")
def health(): return {"status": "ok"}
