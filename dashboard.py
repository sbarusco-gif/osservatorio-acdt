from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import shutil
import uuid
import os
import fitz # PyMuPDF

# Import moduli locali
import models, schemas, database

# Inizializzazione Tabelle Database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - API")

# --- CONFIGURAZIONE CORS (Risolve Errore 403) ---
# Permette alla Dashboard di comunicare con il Backend sul web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In produzione su Render mettiamo "*" per semplicità
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurazione Cartella Storage
UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Mount della cartella per visualizzare i PDF
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# --- FUNZIONE ANALISI AI IN BACKGROUND ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    try:
        print(f"--- AVVIO ANALISI FILE: {file_path} ---")
        doc = fitz.open(file_path)
        testo_estratto = ""
        for pagina in doc.pages(0, 2):
            testo_estratto += pagina.get_text()
        doc.close()

        testo_pulito = testo_estratto.strip()
        descrizione = testo_pulito[:2000] if len(testo_pulito) > 10 else "ATTENZIONE: PDF senza testo leggibile (scansione immagine)."

        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai="CGT Veneto" if "Veneto" in testo_estratto else "CGT Sconosciuta",
            numero_sentenza_ai="Da rilevare",
            massima_ai=descrizione,
            punteggio_confidenza=0.75
        )
        db.add(nuova_scheda)
        
        fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if fascicolo:
            fascicolo.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
        print(f"--- ANALISI COMPLETATA PER: {id_fascicolo} ---")
    except Exception as e:
        print(f"--- ERRORE ANALISI AI: {e} ---")
        db.rollback()
    finally:
        db.close()

# --- ENDPOINT API ---

@app.get("/")
def home():
    # Health check per Render
    return {"status": "Online", "msg": "Benvenuto nell'Osservatorio ACDT"}

@app.post("/v1/fascicoli/upload", response_model=schemas.FascicoloBase)
async def upload_documento(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    
    with open(f_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    nuovo_fascicolo = models.Fascicolo(
        id=f_id, 
        file_originale=f_path, 
        stato=models.StatoFascicolo.In_estrazione
    )
    db.add(nuovo_fascicolo)
    db.commit()
    db.refresh(nuovo_fascicolo)
    
    background_tasks.add_task(analizza_sentenza_ai, nuovo_fascicolo.id, f_path)
    return nuovo_fascicolo

@app.get("/v1/fascicoli", response_model=List[schemas.FascicoloBase])
def leggi_fascicoli(db: Session = Depends(database.get_db)):
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def leggi_scheda(id: uuid.UUID, db: Session = Depends(database.get_db)):
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if not scheda:
        raise HTTPException(status_code=404, detail="Scheda non trovata")
    return scheda

@app.patch("/v1/fascicoli/{id}/validate")
def valida_sentenza(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    
    if not fascicolo or not scheda:
        raise HTTPException(status_code=404, detail="Non trovato")
    
    scheda.organo_corrente = payload.organo or scheda.organo_ai
    scheda.numero_sentenza_corrente = payload.numero_sentenza or scheda.numero_sentenza_ai
    scheda.massima_corrente = payload.massima or scheda.massima_ai
    
    # Rinomina file
    try:
        org_p = scheda.organo_corrente.replace(" ", "_").replace("/", "-").replace("\\", "-")
        num_p = scheda.numero_sentenza_corrente.replace(" ", "_").replace("/", "-").replace("\\", "-")
        nuovo_nome = f"{org_p}_{num_p}.pdf"
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        
        if os.path.exists(fascicolo.file_originale):
            os.rename(fascicolo.file_originale, nuovo_path)
            fascicolo.file_originale = nuovo_path
    except Exception as e:
        print(f"Errore rinomina: {e}")

    fascicolo.stato = models.StatoFascicolo.Validato
    db.commit()
    return {"status": "OK"}

# --- AVVIO SERVER ---
if __name__ == "__main__":
    import uvicorn
    import os
    # Legge la porta assegnata da Render o usa la 10000
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
