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

app = FastAPI(title="Osservatorio ACDT - Pro AI")

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

# --- LOGICA IA AVANZATA ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    try:
        print(f"--- ANALISI SENTENZA: {id_fascicolo} ---")
        doc = fitz.open(file_path)
        # Leggiamo le prime 6 pagine per essere sicuri di prendere tutto il contenuto
        testo = "".join([p.get_text() for p in doc.pages(0, 6)])
        doc.close()

        if not testo or len(testo) < 100:
            raise ValueError("Il PDF non contiene testo leggibile (scansione immagine)")

        prompt_sistema = """
        Sei un magistrato tributarista dell'Ufficio del Massimario. 
        Analizza la sentenza ed estrai i dati tecnici.
        REGOLE OBBLIGATORIE:
        1. MASSIMA: Scrivi una massima tecnica, astratta, universale. Inizia con 'In tema di...'. Non usare nomi di persone.
        2. ORGANO: Identifica chiaramente la Corte (es. CGT II Grado Veneto).
        3. NUMERO: Estrai numero sentenza e anno (es. 123/2024).
        4. DATA: Estrai la data di deposito in formato GG-MM-AAAA.
        5. NORME: Elenca gli articoli di legge principali.

        Rispondi ESCLUSIVAMENTE con un oggetto JSON:
        {"organo": "", "numero": "", "data": "", "massima": "", "norme": ""}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Testo sentenza:\n{testo[:15000]}"}
            ],
            response_format={ "type": "json_object" }
        )
        
        # Analisi della risposta
        risposta_testo = response.choices[0].message.content
        print(f"Risposta IA: {risposta_testo}")
        dati = json.loads(risposta_testo)

        # Salvataggio nel Database
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati.get("organo", "Non rilevato"),
            numero_sentenza_ai=dati.get("numero", "N/D"),
            massima_ai=dati.get("massima", "Errore generazione massima"),
            note_riservate=f"Data: {dati.get('data')} | Norme: {dati.get('norme')}",
            punteggio_confidenza=0.95
        )
        db.add(nuova_scheda)
        
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f:
            f.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
        print("--- SCHEDA SALVATA CON SUCCESSO ---")

    except Exception as e:
        print(f"!!! ERRORE CRITICO IA: {e} !!!")
        # Se fallisce OpenAI, creiamo una scheda di errore per avvisare l'utente
        errore_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai="ERRORE IA",
            massima_ai=f"L'intelligenza artificiale non è riuscita ad analizzare il file. Dettaglio: {str(e)[:200]}",
            note_riservate="VERIFICARE CHIAVE OPENAI"
        )
        db.add(errore_scheda)
        db.commit()
    finally:
        db.close()

# --- ENDPOINTS (Semplificati per stabilità) ---
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
def list_f(db: Session = Depends(database.get_db)): return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: uuid.UUID, db: Session = Depends(database.get_db)): 
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente, s.numero_sentenza_corrente, s.massima_corrente = payload.organo, payload.numero, payload.massima
        # Rinomina file
        data_p = payload.note_riservate.replace("/","-") if payload.note_riservate else "ND"
        nuovo_nome = f"{payload.organo}_{payload.numero}_{data_p}.pdf".replace(" ","_").replace("/","-")
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        if os.path.exists(f.file_originale): os.rename(f.file_originale, nuovo_path)
        f.file_originale, f.stato = nuovo_path, models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    # Ricerca testuale semplice nelle massime validate
    return db.query(models.Scheda).filter(models.Scheda.massima_corrente.ilike(f"%{domanda}%")).all()

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    data = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    res = []
    for s in data:
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == s.id_fascicolo).first()
        res.append({"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente, "file_url": f"/storage/{os.path.basename(f.file_originale)}" if f else ""})
    return res

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
