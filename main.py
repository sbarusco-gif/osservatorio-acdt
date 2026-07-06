import os, uuid, shutil, json, fitz, openai
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import models, schemas, database

app = FastAPI(title="Osservatorio ACDT - Revisione Fissa")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = "storage"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)
app.mount("/storage", StaticFiles(directory=UPLOAD_DIR), name="storage")

@app.on_event("startup")
def startup():
    models.Base.metadata.create_all(bind=database.engine)

def analizza_sentenza_ai(id_fascicolo: str, file_path: str):
    db = database.SessionLocal()
    try:
        # Legge il testo (Inizio e Fine)
        doc = fitz.open(file_path)
        testo = "".join([page.get_text() for page in doc])
        doc.close()
        
        input_ia = testo[:7000] + "\n...\n" + testo[-5000:]
        
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        prompt = "Sei un esperto giurista. Estrai in JSON: organo, numero, data, massima, norme. NON COPIARE L'INTESTAZIONE."
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": input_ia}],
            response_format={ "type": "json_object" }
        )
        res = json.loads(response.choices[0].message.content)

        # AGGIORNA LA SCHEDA ESISTENTE
        s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id_fascicolo).first()
        if s:
            s.organo_ai = res.get("organo")
            s.numero_sentenza_ai = res.get("numero")
            s.massima_ai = res.get("massima")
            s.note_riservate = f"Data: {res.get('data')} | Norme: {res.get('norme')}"
            
            f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id_fascicolo).first()
            if f: f.stato = models.StatoFascicolo.Da_validare
            db.commit()
    except Exception as e:
        print(f"Errore AI: {e}")
    finally: db.close()

@app.post("/v1/fascicoli/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(database.get_db)):
    f_id = str(uuid.uuid4())
    f_path = os.path.join(UPLOAD_DIR, f"{f_id}.pdf")
    with open(f_path, "wb") as b: shutil.copyfileobj(file.file, b)
    
    # 1. CREA FASCICOLO
    n = models.Fascicolo(id=f_id, file_originale=f_path, stato=models.StatoFascicolo.In_estrazione)
    db.add(n)
    
    # 2. CREA SUBITO LA SCHEDA (Così il pannello non scompare)
    s = models.Scheda(id_fascicolo=f_id, organo_ai="In analisi...", numero_sentenza_ai="...", massima_ai="L'IA sta scrivendo la massima, attendi 10 secondi...")
    db.add(s)
    
    db.commit()
    background_tasks.add_task(analizza_sentenza_ai, f_id, f_path)
    return n

@app.get("/v1/fascicoli")
def list_f(db: Session = Depends(database.get_db)): 
    return db.query(models.Fascicolo).all()

@app.get("/v1/fascicoli/{id}/scheda")
def get_s(id: str, db: Session = Depends(database.get_db)): 
    return db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()

@app.patch("/v1/fascicoli/{id}/validate")
def validate(id: str, payload: schemas.ValidazioneInput, db: Session = Depends(database.get_db)):
    f = db.query(models.Fascicolo).filter(models.Fascicolo.id == id).first()
    s = db.query(models.Scheda).filter(models.Scheda.id_fascicolo == id).first()
    if f and s:
        s.organo_corrente, s.numero_sentenza_corrente, s.massima_corrente = payload.organo, payload.numero, payload.massima
        f.stato = models.StatoFascicolo.Validato
        db.commit()
    return {"ok": True}

@app.get("/v1/archivio")
def get_arch(db: Session = Depends(database.get_db)):
    query = db.query(models.Scheda, models.Fascicolo).join(models.Fascicolo).filter(models.Fascicolo.stato == models.StatoFascicolo.Validato).all()
    return [{"organo": s.organo_corrente, "numero": s.numero_sentenza_corrente, "massima": s.massima_corrente, "file_url": f"/storage/{os.path.basename(f.file_originale)}"} for s, f in query]

@app.delete("/v1/archivio/clear")
def clear_archive(db: Session = Depends(database.get_db)):
    db.query(models.Scheda).delete()
    db.query(models.Fascicolo).delete()
    db.commit()
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
