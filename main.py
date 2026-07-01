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

app = FastAPI(title="Osservatorio ACDT - Massimario Professionale")

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

# --- FUNZIONE ANALISI AI ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    try:
        doc = fitz.open(file_path)
        testo_estratto = ""
        for pagina in doc.pages(0, 5):
            testo_estratto += pagina.get_text()
        doc.close()

        prompt_sistema = """
        Sei un esperto del Massimario Tributario. Analizza la sentenza e restituisci un JSON con:
        1. 'organo': Nome della Corte (es. CGT II Grado Veneto).
        2. 'numero': Numero sentenza (es. 123-2024).
        3. 'data': Data deposito/sentenza in formato GG-MM-AAAA (es. 15-05-2024).
        4. 'massima': Redigi una massima tecnica (principio di diritto astratto).
        5. 'norme': Articoli di legge citati.
        Rispondi solo in JSON.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Testo: {testo_estratto[:15000]}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        dati = json.loads(response.choices[0].message.content)

        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati.get("organo"),
            numero_sentenza_ai=dati.get("numero"),
            data_deposito_ai=None, # Gestito come stringa nelle note per semplicità ora
            massima_ai=dati.get("massima"),
            note_riservate=f"Data: {dati.get('data')} | Norme: {dati.get('norme')}",
            punteggio_confidenza=0.98
        )
        db.add(nuova_scheda)
        
        fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if fascicolo:
            fascicolo.stato = models.StatoFascicolo.Da_validare
        db.commit()
    except Exception as e:
        print(f"Errore IA: {e}")
    finally:
        db.close()

# --- ENDPOINT VALIDAZIONE (CON RINOMINA FILE) ---
@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    
    if not f or not s:
        raise HTTPException(status_code=404, detail="Non trovato")

    # 1. Aggiornamento dati correnti
    s.organo_corrente = payload.organo
    s.numero_sentenza_corrente = payload.numero_sentenza
    s.massima_corrente = payload.massima
    # Supponiamo che la data venga passata nelle note o in un nuovo campo
    data_sentenza = payload.note_riservate if payload.note_riservate else "Data-Non-Indicata"

    # 2. Logica di Rinomina Fisica
    try:
        # Pulizia nomi per il file system (rimozione spazi e caratteri illegali)
        org = str(s.organo_corrente).replace(" ", "_").replace("/", "-")
        num = str(s.numero_sentenza_corrente).replace(" ", "_").replace("/", "-")
        dat = str(data_sentenza).replace(" ", "_").replace("/", "-")
        
        nuovo_nome = f"{org}_{num}_{dat}.pdf"
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        
        if os.path.exists(f.file_originale):
            os.rename(f.file_originale, nuovo_path)
            f.file_originale = nuovo_path # Aggiorna il percorso nel DB
    except Exception as e:
        print(f"Errore Rinomina: {e}")

    f.stato = models.StatoFascicolo.Validato
    db.commit()
    return {"status": "success", "nuovo_nome": nuovo_nome}

# --- ALTRI ENDPOINT ---
@app.post("/v1/fascicoli/upload", response_model=schemas.FascicoloBase)
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b:
        shutil.copyfileobj(file.file, b)
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n)
    db.commit()
    db.refresh(n)
    background_tasks.add_task(analizza_sentenza_ai, n.id, f_path)
    return n

@app.get("/v1/fascicoli")
def list_f(db: Session = Depends(database.get_db)):
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: uuid.UUID, db: Session = Depends(database.get_db)):
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
