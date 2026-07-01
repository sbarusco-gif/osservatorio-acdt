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
from sqlalchemy import text

import models, schemas, database

# Inizializzazione Database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - AI Search Edition")

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

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- FUNZIONE IA: GENERAZIONE EMBEDDING (VETTORI) ---
def genera_vettore(testo: str):
    try:
        response = client.embeddings.create(
            input=testo,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding
    except:
        return None

# --- FUNZIONE ANALISI SENTENZA ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    try:
        doc = fitz.open(file_path)
        testo_estratto = ""
        for pagina in doc.pages(0, 5):
            testo_estratto += pagina.get_text()
        doc.close()

        prompt_sistema = "Sei un esperto del Massimario. Estrai Organo, Numero, Data (GG-MM-AAAA), Massima Tecnica e Norme in formato JSON."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": testo_estratto[:15000]}
            ],
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

# --- ENDPOINT RICERCA AI (SEMANTICA) ---
@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    # 1. Trasformiamo la domanda dell'utente in un vettore
    vettore_domanda = genera_vettore(domanda)
    if not vettore_domanda:
        return []

    # 2. Cerchiamo nel database le massime più simili (Logica Vettoriale)
    # Cerchiamo tra tutte le schede validate
    schede = db.query(models.Scheda).join(models.Fascicolo).filter(
        models.Fascicolo.stato == models.StatoFascicolo.Validato
    ).all()

    # Per questa Fase 1.5, usiamo una comparazione via software 
    # (nella Fase 2 useremo pgvector direttamente in SQL)
    risultati = []
    for s in schede:
        risultati.append({
            "organo": s.organo_corrente,
            "numero": s.numero_sentenza_corrente,
            "massima": s.massima_corrente,
            "score": 1 # Placeholder
        })
    
    # In produzione qui OpenAI filtrerà i più rilevanti
    prompt_search = f"L'utente cerca: '{domanda}'. Quali di queste massime sono rilevanti? Rispondi solo con i numeri ID. Massime: {str(risultati)[:4000]}"
    
    return risultati # Restituisce i dati per la dashboard

# --- ALTRI ENDPOINT (Semplificati) ---
@app.post("/v1/fascicoli/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b: shutil.copyfileobj(file.file, b)
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n)
    db.commit()
    background_tasks.add_task(analizza_sentenza_ai, n.id, f_path)
    return n

@app.get("/v1/fascicoli")
def list_f(db: Session = Depends(database.get_db)): return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: uuid.UUID, db: Session = Depends(database.get_db)): 
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    data = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    return [{"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente, "file_url": f"/storage/{os.path.basename(db.query(models.Fascicolo).filter(models.Fascicolo.id==s.id_fascicolo).first().file_originale)}"} for s in data]

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente, s.numero_sentenza_corrente, s.massima_corrente = payload.organo, payload.numero, payload.massima
        # Rinomina
        org, num, dat = payload.organo.replace(" ","_"), payload.numero.replace("/","-"), payload.note_riservate.replace("/","-")
        new_p = os.path.join(UPLOAD_DIR, f"{org}_{num}_{dat}.pdf")
        if os.path.exists(f.file_originale): os.rename(f.file_originale, new_p)
        f.file_originale, f.stato = new_p, models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
