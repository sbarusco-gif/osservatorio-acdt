from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List
import shutil
import uuid
import os
import fitz # PyMuPDF

# Importiamo i nostri moduli locali
import models, schemas, database

# 1. Inizializzazione Tabelle del Database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - API")

# 2. Configurazione Cartella Storage
UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 3. Configurazione Accesso ai File PDF (per visualizzarli nella Dashboard)
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# --- FUNZIONE ANALISI AI IN BACKGROUND ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    # Usiamo una sessione dedicata per l'IA
    db = database.SessionLocal()
    try:
        print(f"--- AVVIO ANALISI FILE: {file_path} ---")
        doc = fitz.open(file_path)
        testo_estratto = ""
        # Leggiamo le prime 2 pagine per estrarre la massima
        for pagina in doc.pages(0, 2):
            testo_estratto += pagina.get_text()
        doc.close()

        testo_pulito = testo_estratto.strip()
        descrizione = testo_pulito[:2000] if len(testo_pulito) > 10 else "ATTENZIONE: PDF senza testo leggibile (scansione immagine)."

        # Creazione record della Scheda con i dati proposti dall'IA
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai="CGT Veneto" if "Veneto" in testo_estratto else "CGT Sconosciuta",
            numero_sentenza_ai="Da rilevare",
            massima_ai=descrizione,
            punteggio_confidenza=0.75,
            versione_modello="PyMuPDF-Extractor-v1"
        )
        db.add(nuova_scheda)
        
        # Aggiornamento stato del fascicolo a 'Da validare'
        fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if fascicolo:
            fascicolo.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
        print(f"--- ANALISI COMPLETATA PER: {id_fascicolo} ---")
    except Exception as e:
        print(f"--- ERRORE DURANTE ANALISI AI: {e} ---")
        db.rollback()
    finally:
        db.close()

# --- ENDPOINT API ---

@app.get("/")
def home():
    return {"status": "Online", "port": 9999}

@app.post("/v1/fascicoli/upload", response_model=schemas.FascicoloBase)
async def upload_documento(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    # Generazione ID unico e salvataggio file
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    
    with open(f_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Creazione record Fascicolo
    nuovo_fascicolo = models.Fascicolo(
        id=f_id, 
        file_originale=f_path, 
        stato=models.StatoFascicolo.In_estrazione
    )
    db.add(nuovo_fascicolo)
    db.commit()
    db.refresh(nuovo_fascicolo)
    
    # Lancio analisi in background
    background_tasks.add_task(analizza_sentenza_ai, nuovo_fascicolo.id, f_path)
    
    return nuovo_fascicolo

@app.get("/v1/fascicoli", response_model=List[schemas.FascicoloBase])
def leggi_tutti_i_fascicoli(db: Session = Depends(database.get_db)):
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def leggi_scheda_ai(id: uuid.UUID, db: Session = Depends(database.get_db)):
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if not scheda:
        raise HTTPException(status_code=404, detail="Scheda non ancora generata dall'IA")
    return scheda

@app.patch("/v1/fascicoli/{id}/validate")
def valida_sentenza(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    fascicolo = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    scheda = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    
    if not fascicolo or not scheda:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    
    # 1. Aggiornamento Dati Correnti (Ufficiali)
    scheda.organo_corrente = payload.organo or scheda.organo_ai
    scheda.numero_sentenza_corrente = payload.numero_sentenza or scheda.numero_sentenza_ai
    scheda.massima_corrente = payload.massima or scheda.massima_ai
    
    # 2. Logica di Rinomina Fisica del File
    try:
        # Pulizia nomi per il file system
        org_p = scheda.organo_corrente.replace(" ", "_").replace("/", "-").replace("\\", "-")
        num_p = scheda.numero_sentenza_corrente.replace(" ", "_").replace("/", "-").replace("\\", "-")
        
        nuovo_nome = f"{org_p}_{num_p}.pdf"
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        
        vecchio_path = fascicolo.file_originale
        if os.path.exists(vecchio_path):
            # Se esiste già un file con lo stesso nome, aggiungiamo un micro-id per non sovrascrivere
            if os.path.exists(nuovo_path) and vecchio_path != nuovo_path:
                nuovo_path = os.path.join(UPLOAD_DIR, f"{org_p}_{num_p}_{str(uuid.uuid4())[:4]}.pdf")
            
            os.rename(vecchio_path, nuovo_path)
            fascicolo.file_originale = nuovo_path
            print(f"--- FILE RINOMINATO IN: {nuovo_path} ---")
    except Exception as e:
        print(f"--- ERRORE RINOMINA: {e} ---")

    fascicolo.stato = models.StatoFascicolo.Validato
    db.commit()
    return {"status": "OK", "file_rinominato": fascicolo.file_originale}

@app.get("/v1/ricerca/simile")
def cerca_simile(testo_ricerca: str, db: Session = Depends(database.get_db)):
    # Ricerca testuale semplice nelle massime validate
    return db.query(models.Scheda).filter(models.Scheda.massima_corrente.contains(testo_ricerca)).all()

# --- AVVIO SERVER (Modificato per il Cloud) ---
if __name__ == "__main__":
    import uvicorn
    import os
    # Render assegna automaticamente una porta, noi la leggiamo. 
    # Se non la trova (tipo sul tuo PC), usa la 8000.
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
