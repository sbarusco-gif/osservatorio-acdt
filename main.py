import os, uuid, shutil, json, fitz, openai
from typing import List
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import models, schemas, database

app = FastAPI(title="Osservatorio ACDT - AI Pro")

# --- CORS CONFIGURATION ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- STORAGE CONFIGURATION ---
UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR): 
    os.makedirs(UPLOAD_DIR)
# Montaggio cartella per download PDF
app.mount("/storage", StaticFiles(directory=UPLOAD_DIR), name="storage")

@app.on_event("startup")
def startup():
    models.Base.metadata.create_all(bind=database.engine)

# --- LOGICA AI MIGLIORATA ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    try:
        doc = fitz.open(file_path)
        num_pages = doc.page_count
        
        # Leggiamo le prime 3 pagine (per l'intestazione)
        testo_inizio = "".join([doc[i].get_text() for i in range(min(3, num_pages))])
        # Leggiamo le ultime 3 pagine (dove di solito c'è il principio di diritto e il PQM)
        testo_fine = ""
        if num_pages > 3:
            testo_fine = "".join([doc[i].get_text() for i in range(max(0, num_pages-3), num_pages)])
        
        testo_totale = testo_inizio + "\n\n[...]\n\n" + testo_fine
        doc.close()

        if not api_key: 
            print("Errore: API KEY mancante")
            return

        client = openai.OpenAI(api_key=api_key)
        
        # PROMPT OTTIMIZZATO PER EVITARE IL COPIA-INCOLLA DELL'INIZIO
        prompt_sistema = """Sei l'Ufficio Massimario di una Corte Tributaria. 
        Il tuo compito è redigere una MASSIMA GIURIDICA tecnica.
        
        REGOLE RIGIDE:
        1. IGNORA l'intestazione, i nomi dei giudici, degli avvocati e delle parti.
        2. NON COPIARE i primi paragrafi della sentenza.
        3. VAI DIRETTAMENTE alla "motivazione in diritto" e al "PQM".
        4. ESTRAI IL PRINCIPIO DI DIRITTO: la regola astratta stabilita dalla Corte.
        
        RESTITUISCI SOLO UN OGGETTO JSON con:
        'organo', 'numero', 'data' (GG/MM/AAAA), 'massima' (tecnica e astratta), 'norme'."""

        response = client.chat.completions.create(
            model="gpt-4o", # Usiamo GPT-4o per una qualità giuridica superiore
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Analizza questa sentenza ed estrai la massima:\n\n{testo_totale[:15000]}"}
            ],
            response_format={ "type": "json_object" },
            temperature=0.2 # Bassa temperatura = più precisione, meno invenzioni
        )
        
        d = json.loads(response.choices[0].message.content)
        
        # Salvataggio bozza AI
        nuova = models.Scheda(
            id_fascicolo=id_fascicolo, 
            organo_ai=d.get("organo"), 
            numero_sentenza_ai=d.get("numero"), 
            massima_ai=d.get("massima"), 
            note_riservate=f"Data: {d.get('data')} | Norme: {d.get('norme')}"
        )
        db.add(nuova)
        
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f: 
            f.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
    except Exception as e:
        print(f"Errore durante l'analisi AI: {e}")
    finally: 
        db.close()

# --- ENDPOINTS ---

@app.get("/")
def health(): 
    return {"status": "ok", "message": "Backend Operativo"}

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
    
    # Avvia l'analisi IA in background per non bloccare l'utente
    background_tasks.add_task(analizza_sentenza_ai, n.id, f_path)
    return n

@app.get("/v1/fascicoli")
def list_f(db: Session = Depends(database.get_db)): 
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: str, db: Session = Depends(database.get_db)): 
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    query = db.query(models.Scheda, models.Fascicolo).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    res = []
    for s, f in query:
        res.append({
            "id": s.id,
            "organo": s.organo_corrente, 
            "numero": s.numero_sentenza_corrente, 
            "massima": s.massima_corrente, 
            "file_url": f"/storage/{os.path.basename(f.file_originale)}"
        })
    return res

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: str, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if not f or not s:
        raise HTTPException(status_code=404, detail="Fascicolo non trovato")
    
    s.organo_corrente = payload.organo
    s.numero_sentenza_corrente = payload.numero
    s.massima_corrente = payload.massima
    f.stato = models.StatoFascicolo.Validato
    db.commit()
    return {"ok": True}

# --- NUOVO: CANCELLA TUTTO L'ARCHIVIO ---
@app.delete("/v1/archivio/clear")
def clear_archive(db: Session = Depends(database.get_db)):
    try:
        # Cancella tutte le schede e i fascicoli
        db.query(models.Scheda).delete()
        db.query(models.Fascicolo).delete()
        db.commit()
        
        # Opzionale: Svuota la cartella storage dai file fisici
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            try:
                if os.path.isfile(file_path): os.unlink(file_path)
            except Exception as e: print(f"Errore cancellazione file: {e}")
            
        return {"message": "Archivio e file fisici eliminati correttamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    schede = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    # Semplice ricerca testuale (in produzione usare Vector Search)
    return [s for s in schede if domanda.lower() in (s.massima_corrente or "").lower()][:10]

if __name__ == "__main__":
    import uvicorn
    # Render imposta automaticamente la variabile d'ambiente PORT
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
