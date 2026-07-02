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

# --- FUNZIONE IA MASSIMARIO (ESEGUITA SUBITO) ---
def analizza_sentenza_diretta(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    
    try:
        print(f"--- [STEP 1] APERTURA FILE: {file_path} ---")
        doc = fitz.open(file_path)
        testo_estratto = ""
        for pagina in doc.pages(0, 5): # Leggiamo le prime 6 pagine
            testo_estratto += pagina.get_text()
        doc.close()

        print(f"--- [STEP 2] TESTO ESTRATTO (Primi 200 car.): {testo_estratto[:200]} ---")

        if len(testo_estratto.strip()) < 50:
            raise ValueError("Il PDF non contiene testo (forse è una scansione immagine).")

        if not api_key:
            raise ValueError("Manca la variabile OPENAI_API_KEY su Render.")

        print("--- [STEP 3] CHIAMATA OPENAI ---")
        client = openai.OpenAI(api_key=api_key)
        
        prompt_sistema = """
        Sei un Magistrato dell'Ufficio del Massimario. 
        Analizza la sentenza ed estrai i dati tecnici ESCLUSIVAMENTE in JSON.
        REGOLE PER LA MASSIMA:
        - Deve essere un principio di diritto astratto (In tema di..., il principio stabilisce che...).
        - NON copiare il testo della sentenza.
        - NON usare nomi di persone.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Sentenza:\n{testo_estratto[:15000]}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        dati = json.loads(response.choices[0].message.content)
        print(f"--- [STEP 4] RISPOSTA IA: {dati} ---")

        # Salvataggio dati IA
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati.get("organo", "Non rilevato"),
            numero_sentenza_ai=dati.get("numero", "N/D"),
            massima_ai=dati.get("massima", "Errore generazione massima"),
            note_riservate=f"Data: {dati.get('data')} | Norme: {dati.get('norme')}",
            punteggio_confidenza=0.98
        )
        db.add(nuova_scheda)
        
        # Cambiamo stato
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f: f.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
        print("--- [STEP 5] TUTTO SALVATO CORRETTAMENTE ---")

    except Exception as e:
        print(f"--- [ERRORE] {str(e)} ---")
        # Salviamo l'errore nella massima così l'utente lo vede nella dashboard
        db.add(models.Scheda(id_fascicolo=id_fascicolo, massima_ai=f"ERRORE: {str(e)}"))
        db.commit()
    finally:
        db.close()

# --- ENDPOINTS ---

@app.post("/v1/fascicoli/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b:
        shutil.copyfileobj(file.file, b)
    
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n)
    db.commit()
    db.refresh(n)
    
    # Eseguiamo l'analisi
    background_tasks.add_task(analizza_sentenza_diretta, n.id, f_path)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
