import os
import uuid
import shutil
import json
import fitz
import openai
from typing import List
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import models, schemas, database

app = FastAPI(title="Osservatorio ACDT - v6")

# 1. ABILITAZIONE CORS (Immediata)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. CARTELLE E MOUNT (Immediati)
UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# 3. AVVIO RITARDATO DATABASE (Non blocca la porta 10000)
@app.on_event("startup")
def startup_db():
    try:
        models.Base.metadata.create_all(bind=database.engine)
        print("DATABASE: Tabelle create con successo.")
    except Exception as e:
        print(f"DATABASE ERROR: {e} (Il database potrebbe essere in sleep)")

# --- FUNZIONE IA PROFESSIONALE ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    try:
        doc = fitz.open(file_path)
        testo = "".join([p.get_text() for p in doc.pages(0, 7)])
        doc.close()

        if not api_key or len(testo) < 100:
            raise ValueError("Testo assente o Chiave API mancante")

        client = openai.OpenAI(api_key=api_key)
        prompt = """Sei l'Ufficio del Massimario della Corte di Giustizia Tributaria. 
        Analizza ed estrai ESCLUSIVAMENTE in JSON:
        'organo' (Corte completa), 'numero' (es. 123/2024), 'data' (GG-MM-AAAA), 
        'massima' (Tecnica, astratta, linguaggio formale), 'norme' (Articoli citati)."""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo[:15000]}],
            response_format={ "type": "json_object" }
        )
        dati = json.loads(response.choices[0].message.content)

        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati.get("organo"),
            numero_sentenza_ai=dati.get("numero"),
            massima_ai=dati.get("massima"),
            note_riservate=f"Data: {dati.get('data')} | Norme: {dati.get('norme')}"
        )
        db.add(nuova_scheda)
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f: f.stato = models.StatoFascicolo.Da_validare
        db.commit()
    except Exception as e:
        print(f"ERRORE IA: {e}")
        db.add(models.Scheda(id_fascicolo=id_fascicolo, massima_ai=f"Analisi fallita. Riprova. Errore: {e}"))
        db.commit()
    finally:
        db.close()

# --- ENDPOINTS ---
@app.get("/")
def health(): return {"status": "ok"} # Risponde subito a Render

@app.post("/v1/fascicoli/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b: shutil.copyfileobj(file.file, b)
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n); db.commit(); db.refresh(n)
    background_tasks.add_task(analizza_sentenza_ai, n.id, f_path)
    return n

@app.get("/v1/fascicoli")
def list_f(db: Session = Depends(database.get_db)): return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: uuid.UUID, db: Session =
