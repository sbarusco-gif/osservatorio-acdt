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

# Inizializzazione Database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - AI Search Edition")

# --- CONFIGURAZIONE CORS ---
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

# Configurazione OpenAI
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- FUNZIONE ANALISI SENTENZA CON IA ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    try:
        doc = fitz.open(file_path)
        testo = ""
        for pagina in doc.pages(0, 5): testo += pagina.get_text()
        doc.close()

        prompt = """Sei un esperto del Massimario Tributario. 
        Estrai in JSON: organo, numero, data (GG-MM-AAAA), massima (tecnica e astratta), norme.
        Usa un linguaggio giuridico formale."""
        
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
        print(f"Errore: {e}")
    finally:
        db.close()

# --- ENDPOINT RICERCA INTELLIGENTE AI (SEMANTICA) ---
@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    # Recuperiamo tutte le massime ufficiali (validate)
    schede = db.query(models.Scheda).join(models.Fascicolo).filter(
        models.Fascicolo.stato == models.StatoFascicolo.Validato
    ).all()
    
    if not schede: return []

    # Prepariamo un elenco sintetico per OpenAI
    archivio_testo = ""
    for s in schede:
        archivio_testo += f"ID: {s.id_fascicolo} | Massima: {s.massima_corrente}\n"

    prompt_ricerca = f"""
    Agisci come un motore di ricerca semantico. L'utente cerca sentenze che trattano di: '{domanda}'.
    Dato questo archivio, seleziona i 5 ID più pertinenti.
    Restituisci ESCLUSIVAMENTE un JSON con questo formato: {{"risultati": ["id1", "id2"]}}
    Archivio:\n{archivio_testo}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_ricerca}],
        response_format={ "type": "json_object" }
    )
    
    ids_validi = json.loads(response.choices[0].message.content).get("risultati", [])
    # Recuperiamo le schede complete dal database per gli ID trovati
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo.in_(ids_validi)).all()

# --- ALTRI ENDPOINT ---
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
    data = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    res = []
    for s in data:
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == s.id_fascicolo).first()
        res.append({
            "organo": s.organo_corrente, 
            "numero": s.numero_sentenza_corrente, 
            "massima": s.massima_corrente, 
            "file_url": f"/storage/{os.path.basename(f.file_originale)}" if f else ""
        })
    return res

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente = payload.organo
        s.numero_sentenza_corrente = payload.numero
        s.massima_corrente = payload.massima
        # Rinomina file in base ai dati ufficiali
        data_pulita = payload.note_riservate.replace("/","-") if payload.note_riservate else "ND"
        nuovo_nome = f"{payload.organo}_{payload.numero}_{data_pulita}.pdf".replace(" ","_").replace("/","-")
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        if os.path.exists(f.file_originale): os.rename(f.file_originale, nuovo_path)
        f.file_originale = nuovo_path
        f.stato = models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

@app.get("/")
def home(): return {"status": "Online"}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
