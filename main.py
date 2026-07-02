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

app = FastAPI(title="ACDT Pro")

# 1. CORS IMMEDIATO
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. CARTELLE
UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# 3. DATABASE: INIZIALIZZAZIONE SICURA
@app.get("/")
def health_check():
    # Questo serve a svegliare il DB se è in sleep senza bloccare l'avvio
    try:
        models.Base.metadata.create_all(bind=database.engine)
        return {"status": "Online"}
    except:
        return {"status": "Database Initializing"}

# --- LOGICA IA ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    try:
        doc = fitz.open(file_path)
        testo = "".join([p.get_text() for p in doc.pages(0, 5)])
        doc.close()
        
        if not api_key: return
        client = openai.OpenAI(api_key=api_key)
        
        prompt = """Sei l'Ufficio del Massimario CGT. Estrai in JSON: 
        'organo', 'numero', 'data' (GG-MM-AAAA), 'massima' (tecnica e astratta), 'norme'."""
        
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
    except Exception as e: print(f"Errore: {e}")
    finally: db.close()

# --- ENDPOINTS ---
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

@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    schede = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    # Ricerca rapida testuale
    return [s for s in schede if domanda.lower() in s.massima_corrente.lower()][:10]

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
        # Rinomina file fisica (Organo_Numero_Data)
        d_p = str(payload.note_riservate).replace("/","-") if payload.note_riservate else "ND"
        nuovo_nome = f"{payload.organo}_{payload.numero}_{d_p}.pdf".replace(" ","_").replace("/","-")
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        if os.path.exists(f.file_originale): os.rename(f.file_originale, nuovo_path)
        f.file_originale, f.stato = nuovo_path, models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    # Render richiede l'avvio su 0.0.0.0
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
