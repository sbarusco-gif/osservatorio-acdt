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

app = FastAPI(title="Osservatorio ACDT - v5")

# --- CONFIGURAZIONE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Creazione tabelle all'avvio senza bloccare il server
@app.on_event("startup")
def startup_event():
    models.Base.metadata.create_all(bind=database.engine)

UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# --- FUNZIONE IA MASSIMARIO ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    try:
        doc = fitz.open(file_path)
        testo = "".join([p.get_text() for p in doc.pages(0, 6)])
        doc.close()

        if not api_key: return

        client = openai.OpenAI(api_key=api_key)
        prompt = """Agisci come l'Ufficio del Massimario. Estrai in JSON: 
        'organo', 'numero', 'data' (GG-MM-AAAA), 'massima' (Tecnica e astratta), 'norme'."""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": testo[:12000]}],
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
        print(f"Errore IA: {e}")
    finally:
        db.close()

# --- ENDPOINTS ---
@app.get("/")
def health(): return {"status": "ok"}

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
def get_s(id: uuid.UUID, db: Session = Depends(database.get_db)): 
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    query = db.query(models.Scheda, models.Fascicolo).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    return [{"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente, "file_url": f"/storage/{os.path.basename(f.file_originale)}"} for s, f in query]

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente, s.numero_sentenza_corrente, s.massima_corrente = payload.organo, payload.numero, payload.massima
        f.stato = models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    # Forza la porta 10000 che Render si aspetta
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
