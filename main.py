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

# Import moduli locali
import models, schemas, database

# Inizializzazione Database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Osservatorio ACDT - AI Search Edition")

# --- CONFIGURAZIONE CORS (Risolto errore riga 21) ---
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

# --- FUNZIONE ANALISI AI (MASSIMA TECNICA) ---
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
        3. 'data': Data sentenza in formato GG-MM-AAAA.
        4. 'massima': Redigi una massima tecnica giuridica (principio astratto).
        5. 'norme': Articoli citati.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": testo_estratto[:15000]}
            ],
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
        print(f"Errore IA: {e}")
    finally:
        db.close()

# --- ENDPOINT RICERCA AI (SEMANTICA) ---
@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    # Recuperiamo tutte le massime validate
    schede = db.query(models.Scheda).join(models.Fascicolo).filter(
        models.Fascicolo.stato == models.StatoFascicolo.Validato
    ).all()
    
    if not schede: return []

    # Chiediamo a OpenAI di trovare le più pertinenti tra quelle in archivio
    elenco_massime = ""
    for s in schede:
        elenco_massime += f"ID: {s.id_fascicolo} | Massima: {s.massima_corrente}\n"

    prompt_ricerca = f"""
    Dato questo elenco di massime giuridiche, quali sono le più pertinenti per rispondere alla domanda: '{domanda}'?
    Restituisci solo un JSON con un array di ID chiamati 'risultati'.
    Massime:\n{elenco_massime}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt_ricerca}],
        response_format={ "type": "json_object" }
    )
    
    ids_pertinenti = json.loads(response.choices[0].message.content).get("risultati", [])
    
    # Recuperiamo gli oggetti completi dal DB per gli ID trovati
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo.in_(ids_pertinenti)).all()

# --- ENDPOINT STANDARD ---
@app.get("/")
def home(): return {"status": "Online"}

@app.post("/v1/fascicoli/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b: shutil.copyfileobj(file.file, b)
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n)
    db.commit()
    db.refresh(n)
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
        res.append({"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente, "file_url": f"/storage/{os.path.basename(f.file_originale)}"})
    return res

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: uuid.UUID, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente, s.numero_sentenza_corrente, s.massima_corrente = payload.organo, payload.numero, payload.massima
        # Rinomina file: Organo_Numero_Data.pdf
        data_pulita = payload.note_riservate.replace("/","-") if payload.note_riservate else "ND"
        nuovo_nome = f"{payload.organo}_{payload.numero}_{data_pulita}.pdf".replace(" ", "_").replace("/","-")
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        if os.path.exists(f.file_originale): os.rename(f.file_originale, nuovo_path)
        f.file_originale, f.stato = nuovo_path, models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
