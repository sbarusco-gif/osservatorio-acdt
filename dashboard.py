import streamlit as st
import requests
import pandas as pd
import os

# --- CONFIGURAZIONE ---
# Recupera l'URL del backend dalle impostazioni di Render
API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:9999").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# --- SIDEBAR: CARICAMENTO ---
st.sidebar.header("📥 Caricamento Sentenza")
u_file = st.sidebar.file_uploader("Seleziona il PDF", type="pdf")

if st.sidebar.button("Invia all'IA"):
    if u_file:
        try:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            r = requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                st.sidebar.success("Caricato! Ricarica la pagina.")
                st.rerun()
            else:
                st.sidebar.error(f"Errore server: {r.status_code}")
        except Exception as e:
            st.sidebar.error(f"Errore connessione: {e}")

# --- RECUPERO DATI DAL BACKEND ---
dati_json = []
try:
    res = requests.get(f"{API_URL}/v1/fascicoli", headers=HEADERS, timeout=15)
    if res.status_code == 200:
        dati_json = res.json()
except:
    dati_json = []

# --- INTERFACCIA ---
if not dati_json:
    st.info("👋 Benvenuto! Carica un PDF per iniziare.")
else:
    df = pd.DataFrame(dati_json)
    st.subheader(f"Elenco Documenti ({len(dati_json)})")
    st.dataframe(df[["id", "stato", "data_caricamento"]], use_container_width=True)

    st.divider()

    id_list = [f["id"] for f in dati_json]
    id_scelto = st.selectbox("Seleziona ID Fascicolo", id_list)

    if id_scelto:
        # Recupero della scheda (sempre tramite Backend)
        s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_scelto}/scheda", headers=HEADERS)
        if s_res.status_code == 200:
            scheda = s_res.json()
            col1, col2 = st.columns(2)
            with col1:
                st.info("### 🤖 Dati IA")
                st.write(f"**Organo:** {scheda.get('organo_ai')}")
                st.write(f"**Massima:** {scheda.get('massima_ai')}")
            with col2:
                st.success("### ✅ Validazione")
                v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                v_max = st.text_area("Massima", value=scheda.get('massima_ai'), height=300)
                if st.button("SALVA"):
                    p = {"organo": v_org, "massima": v_max}
                    requests.patch(f"{API_URL}/v1/fascicoli/{id_scelto}/validate", json=p, headers=HEADERS)
                    st.success("Salvato!")
                    st.rerun()
