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

app = FastAPI(title="Osservatorio ACDT - Massimario AI")

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

def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    try:
        doc = fitz.open(file_path)
        testo_estratto = ""
        for pagina in doc.pages(0, 5):
            testo_estratto += pagina.get_text()
        doc.close()

        # PROMPT TECNICO PER MASSIMARIO
        prompt_sistema = """
        Sei un esperto dell'Ufficio del Massimario della Corte di Giustizia Tributaria. 
        Analizza la sentenza e restituisci un JSON con:
        1. 'organo': Nome della Corte.
        2. 'numero': Numero e anno sentenza.
        3. 'norme': Elenco puntuale delle norme/articoli applicati (es: 'Art. 7 d.lgs. 546/1992').
        4. 'massima': Redigi una MASSIMA TECNICA. Deve essere un principio astratto, senza nomi di persone. 
           Inizia con 'In tema di [argomento]...' e usa un linguaggio giuridico formale.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Testo sentenza: {testo_estratto[:15000]}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        dati_ia = json.loads(response.choices[0].message.content)

        # Salvataggio (Nota: usiamo massima_ai per la massima e note_riservate per le norme temporaneamente)
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati_ia.get("organo"),
            numero_sentenza_ai=dati_ia.get("numero"),
            massima_ai=dati_ia.get("massima"),
            note_riservate=f"Norme di riferimento: {dati_ia.get('norme')}",
            punteggio_confidenza=0.98
        )
        db.add(nuova_scheda)
        
        fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if fascicolo:
            fascicolo.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
    except Exception as e:
        print(f"Errore: {e}")
        db.rollback()
    finally:
        db.close()

@app.get("/")
def home():
    return {"status": "Online"}

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

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if s:
        s.massima_corrente = payload.massima
        s.organo_corrente = payload.organo
        s.numero_sentenza_corrente = payload.numero_sentenza
        f.stato = models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

@app.get("/v1/ricerca")
def ricerca(query: str, db: Session = Depends(database.get_db)):
    return db.query(models.Scheda).filter(
        (models.Scheda.massima_corrente.ilike(f"%{query}%")) | 
        (models.Scheda.note_riservate.ilike(f"%{query}%"))
    ).all()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
