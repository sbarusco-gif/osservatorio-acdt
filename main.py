import os
import uuid
import shutil
import fitz  # PyMuPDF
from typing import List
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Import moduli locali
import models
import schemas
import database

# 1. Inizializzazione Database (Solo il Backend tocca il DB)
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - API")

# 2. Configurazione CORS (Risolve errore 403 e blocchi comunicazione)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permette alla Dashboard su Render di parlare con questo Backend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Configurazione Cartella Storage
UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 4. Accesso ai file PDF (per visualizzarli nella Dashboard)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# --- FUNZIONE ANALISI AI IN BACKGROUND ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    # L'analisi in background richiede una sessione DB dedicata
    db = database.SessionLocal()
    try:
        print(f"--- AVVIO ANALISI AI PER IL FILE: {file_path} ---")
        doc = fitz.open(file_path)
        testo_estratto = ""
        # Leggiamo le prime 2 pagine per estrarre la massima
        for pagina in doc.pages(0, 2):
            testo_estratto += pagina.get_text()
        doc.close()

        testo_pulito = testo_estratto.strip()
        descrizione = testo_pulito[:2000] if len(testo_pulito) > 10 else "ATTENZIONE: PDF senza testo leggibile (scansione immagine)."

        # Creazione della Scheda AI
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai="CGT Veneto" if "Veneto" in testo_estratto else "CGT Sconosciuta",
            numero_sentenza_ai="Da rilevare",
            massima_ai=descrizione,
            punteggio_confidenza=0.75
        )
        db.add(nuova_scheda)
        
        # Cambiamo lo stato del fascicolo
        fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if fascicolo:
            fascicolo.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
        print(f"--- ANALISI AI COMPLETATA PER: {id_fascicolo} ---")
    except Exception as e:
        print(f"--- ERRORE ANALISI AI: {e} ---")
        db.rollback()
    finally:
        db.close()

# --- ENDPOINT API ---

@app.get("/")
def home():
    return {"status": "Online", "msg": "Backend Osservatorio ACDT pronto"}

@app.post("/v1/fascicoli/upload", response_model=schemas.FascicoloBase)
async def upload_documento(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    # Salvataggio file con ID unico
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    
    with open(f_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Registrazione nel Database
    nuovo_fascicolo = models.Fascicolo(
        id=f_id, 
        file_originale=f_path, 
        stato=models.StatoFascicolo.In_estrazione
    )
    db.add(nuovo_fascicolo)
    db.commit()
    db.refresh(nuovo_fascicolo)
    
    # Avvio analisi automatica in background
    background_tasks.add_task(analizza_sentenza_ai, nuovo_fascicolo.id, f_path)
    
    return nuovo_fascicolo

@app.get("/v1/fascicoli", response_model=List[schemas.FascicoloBase])
def leggi_tutti_i_fascicoli(db: Session = Depends(database.get_db)):
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def leggi_scheda_ai(id: uuid.UUID, db: Session = Depends(database.get_db)):
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if not scheda:
        raise HTTPException(status_code=404, detail="Scheda non trovata")
    return scheda

@app.patch("/v1/fascicoli/{id}/validate")
def valida_sentenza(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    
    if not fascicolo or not scheda:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    
    # 1. Salvataggio dati corretti dall'utente
    scheda.organo_corrente = payload.organo or scheda.organo_ai
    scheda.numero_sentenza_corrente = payload.numero_sentenza or scheda.numero_sentenza_ai
    scheda.massima_corrente = payload.massima or scheda.massima_ai
    
    # 2. Rinomina fisica del file PDF in base ai nuovi riferimenti
    try:
        org_p = scheda.organo_corrente.replace(" ", "_").replace("/", "-").replace("\\", "-")
        num_p = scheda.numero_sentenza_corrente.replace(" ", "_").replace("/", "-").replace("\\", "-")
        nuovo_nome = f"{org_p}_{num_p}.pdf"
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        
        if os.path.exists(fascicolo.file_originale):
            os.rename(fascicolo.file_originale, nuovo_path)
            fascicolo.file_originale = nuovo_path # Aggiorniamo il percorso nel DB
    except Exception as e:
        print(f"Errore rinomina: {e}")

    fascicolo.stato = models.StatoFascicolo.Validato
    db.commit()
    return {"status": "success", "file": nuovo_path if 'nuovo_path' in locals() else fascicolo.file_originale}

# --- AVVIO SERVER ---
if __name__ == "__main__":
    import uvicorn
    # Render assegna la porta automaticamente tramite variabile d'ambiente
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
