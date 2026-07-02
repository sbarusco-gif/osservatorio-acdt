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

# --- MOTORE IA: UFFICIO DEL MASSIMARIO ---
def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    api_key = os.getenv("OPENAI_API_KEY")
    try:
        # A. Estrazione testo migliorata (leggiamo fino a 10 pagine)
        doc = fitz.open(file_path)
        testo = ""
        for pagina in doc.pages(0, 9):
            testo += pagina.get_text("text")
        doc.close()

        if not api_key or len(testo.strip()) < 100:
            raise ValueError("Testo illeggibile o API Key mancante")

        client = openai.OpenAI(api_key=api_key)

        # B. PROMPT TECNICO RIGOROSO
        prompt_sistema = """
        Sei un Magistrato Tributarista addetto all'Ufficio del Massimario. 
        Il tuo compito è analizzare la sentenza e redigere una MASSIMA TECNICA.
        
        REGOLE PER LA MASSIMA:
        - Deve essere un principio di diritto astratto e universale.
        - Inizia SEMPRE con 'In tema di [argomento tributario]...'.
        - NON citare i nomi delle parti (es. Rossi, Comune di X).
        - Usa termini tecnici: 'il contribuente', 'l'ufficio impositore', 'il principio di soccombenza'.
        - NON copiare il testo della sentenza, devi RIELABORARE il concetto giuridico.

        DATI DA ESTRARRE:
        - organo: Nome completo della Corte (es. Corte di Giustizia Tributaria di II Grado del Veneto).
        - numero: Numero/Anno della sentenza (es. 1234/2024).
        - data: Data di DEPOSITO della sentenza (formato GG/MM/AAAA).

        RISPONDI ESCLUSIVAMENTE IN FORMATO JSON:
        {
          "organo": "string",
          "numero": "string",
          "data": "string",
          "massima": "string",
          "norme": "string"
        }
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini", # Modello avanzato per comprensione giuridica
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Testo integrale della sentenza da massimare:\n\n{testo[:15000]}"}
            ],
            response_format={ "type": "json_object" }
        )

        dati_ia = json.loads(response.choices[0].message.content)

        # C. Salvataggio nel Database
        nuova_scheda = models.Scheda(
            id_fascicolo=id_fascicolo,
            organo_ai=dati_ia.get("organo"),
            numero_sentenza_ai=dati_ia.get("numero"),
            massima_ai=dati_ia.get("massima"),
            note_riservate=f"Data: {dati_ia.get('data')} | Norme: {dati_ia.get('norme')}",
            punteggio_confidenza=0.98
        )
        db.add(nuova_scheda)
        
        f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
        if f: f.stato = models.StatoFascicolo.Da_validare
        
        db.commit()
    except Exception as e:
        print(f"ERRORE IA: {e}")
        db.add(models.Scheda(id_fascicolo=id_fascicolo, massima_ai=f"ERRORE ANALISI: Il PDF potrebbe essere un'immagine o mancano credenziali OpenAI. Dettaglio: {e}"))
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
        # Rinomina file fisica (Organo_Numero_Data)
        d_p = str(payload.note_riservate).replace("/","-") if payload.note_riservate else "ND"
        nuovo_nome = f"{payload.organo}_{payload.numero}_{d_p}.pdf".replace(" ","_").replace("/","-")
        nuovo_path = os.path.join(UPLOAD_DIR, nuovo_nome)
        if os.path.exists(f.file_originale): os.rename(f.file_originale, nuovo_path)
        f.file_originale, f.stato = nuovo_path, models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

@app.get("/v1/ricerca/ai")
def ricerca_ai(domanda: str, db: Session = Depends(database.get_db)):
    schede = db.query(models.Scheda).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    return [s for s in schede if domanda.lower() in s.massima_corrente.lower()][:10]

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    query = db.query(models.Scheda, models.Fascicolo).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    return [{"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente, "file_url": f"/storage/{os.path.basename(f.file_originale)}"} for s, f in query]

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
