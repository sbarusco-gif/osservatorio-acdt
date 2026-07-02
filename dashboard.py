import streamlit as st
import requests
import pandas as pd
import os

# Configurazione URL
API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:10000").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# Funzione per chiamate sicure al backend
def safe_get(endpoint, params=None):
    try:
        r = requests.get(f"{API_URL}{endpoint}", params=params, headers=HEADERS, timeout=10)
        if r.status_code == 200: return r.json()
        return None
    except: return None

t_gest, t_arch = st.tabs(["📋 Gestione e Validazione", "📚 Archivio Massime"])

with t_gest:
    st.sidebar.header("Carica PDF")
    u_file = st.sidebar.file_uploader("Scegli file", type="pdf")
    if st.sidebar.button("Avvia Analisi IA"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.sidebar.success("Inviato! Attendi 10 secondi e ricarica.")
    
    # Lista fascicoli
    dati = safe_get("/v1/fascicoli")
    if dati:
        da_v = [f for f in dati if f['stato'] != 'Validato']
        if da_v:
            st.subheader("Documenti da revisionare")
            df = pd.DataFrame(da_v)
            st.dataframe(df[["id", "stato"]], use_container_width=True)
            
            id_sel = st.selectbox("Seleziona ID", [f["id"] for f in da_v])
            scheda = safe_get(f"/v1/fascicoli/{id_sel}/scheda")
            
            if scheda:
                c1, c2 = st.columns(2)
                with c1:
                    st.info("### 🤖 Bozza IA")
                    st.write(f"**Corte:** {scheda.get('organo_ai')}")
                    st.write(f"**Numero:** {scheda.get('numero_sentenza_ai')}")
                    st.markdown(f"> {scheda.get('massima_ai')}")
                with c2:
                    st.success("### ✅ Validazione")
                    v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                    v_num = st.text_input("Numero", value=scheda.get('numero_sentenza_ai'))
                    v_max = st.text_area("Massima Tecnica", value=scheda.get('massima_ai'), height=250)
                    if st.button("SALVA E ARCHIVIA"):
                        p = {"organo": v_org, "numero": v_num, "massima": v_max}
                        requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=p, headers=HEADERS)
                        st.rerun()
        else:
            st.info("Nessun documento da validare.")
    else:
        st.warning("Connessione al server in corso...")

with t_arch:
    st.header("📚 Archivio Massime")
    archivio = safe_get("/v1/archivio")
    if archivio:
        for item in archivio:
            st.subheader(f"{item['organo']} - {item['numero']}")
            st.write(item['massima'])
            st.divider()
    else:
        st.write("L'archivio è vuoto.")
