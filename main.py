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

app = FastAPI(title="Osservatorio ACDT - v3")

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

# --- MOTORE IA MASSIMARIO ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    
    try:
        doc = fitz.open(file_path)
        testo = "".join([p.get_text() for p in doc.pages(0, 7)]) # Leggiamo fino a 8 pagine
        doc.close()

        if len(testo.strip()) < 100:
            raise ValueError("Il PDF non ha testo leggibile (scansione immagine).")

        if not api_key:
            raise ValueError("Chiave API OpenAI mancante.")

        client = openai.OpenAI(api_key=api_key)
        
        prompt_sistema = """
        Agisci come l'Ufficio del Massimario della Corte di Giustizia Tributaria. 
        Analizza il testo ed estrai questi dati ESCLUSIVAMENTE in formato JSON:
        - organo: Nome completo della Corte giudicante.
        - numero: Numero sentenza/anno (es. 123/2024).
        - data: Data deposito sentenza (formato GG-MM-AAAA).
        - massima: Una MASSIMA TECNICA GIURIDICA. Deve essere un principio astratto, universale, senza nomi di persone. Usa linguaggio formale.
        - norme: Articoli di legge citati (es. Art. 13 D.Lgs 201/2011).
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Testo sentenza:\n{testo[:15000]}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        dati = json.loads(response.choices[0].message.content)

        # Salvataggio dati estratti
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati.get("organo", "Non rilevato"),
            numero_sentenza_ai=dati.get("numero", "N/D"),
            massima_ai=dati.get("massima", "Errore generazione massima"),
            note_riservate=f"Data: {dati.get('data')} | Norme: {dati.get('norme')}"
        )
        db.add(nuova_scheda)
        
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f: f.stato = models.StatoFascicolo.Da_validare
        
        db.commit()

    except Exception as e:
        print(f"ERRORE IA: {e}")
        # In caso di errore, creiamo una scheda minima per non bloccare il sistema
        db.add(models.Scheda(id_fascicolo=id_fascicolo, organo_ai="ERRORE", massima_ai=f"Analisi fallita: {str(e)}"))
        db.commit()
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
def list_f(db: Session = Depends(database.get_db)):
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: uuid.UUID, db: Session = Depends(database.get_db)): 
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if not scheda: raise HTTPException(status_code=404)
    return scheda

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
    res = []
    for s in data:
        res.append({"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente})
    return res
