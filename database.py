import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Recupero l'URL del Database
# Se siamo sul Web (Cloud), cercherà la variabile 'DATABASE_URL'.
# Se siamo in locale, userà l'indirizzo del tuo Docker.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://admin_acdt:password_segreta_123@localhost:5432/osservatorio_db"
)

# 2. Correzione per i provider Cloud (come Render o Railway)
# Molti provider usano 'postgres://', ma SQLAlchemy moderno richiede 'postgresql://'
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 3. Creazione del motore di connessione (Engine)
# 'pool_pre_ping=True' serve a ricollegarsi automaticamente se la connessione cade
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_pre_ping=True
)

# 4. Configurazione della sessione di lavoro
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 5. Definizione della Base per i modelli (usata in models.py)
Base = declarative_base()

# 6. Funzione per ottenere una connessione al Database (Dependency Injection)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()