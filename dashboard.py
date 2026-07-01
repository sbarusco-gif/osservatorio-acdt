import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="Osservatorio ACDT", layout="wide")

# --- FORZATURA INDIRIZZO ---
# Sostituisci il link qui sotto con quello del tuo backend (quello che finisce con .onrender.com)
API_URL = "https://osservatorio-dashboard.onrender.com/" 

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# Visualizziamo l'URL a video per essere sicuri che il software stia usando quello giusto
st.sidebar.write(f"Connesso a: {API_URL}")

# --- RECUPERO DATI ---
dati_json = []
try:
    res = requests.get(f"{API_URL}/v1/fascicoli", timeout=10)
    if res.status_code == 200:
        dati_json = res.json()
except Exception as e:
    st.error(f"Errore di connessione al server: {e}")

# --- SIDEBAR: CARICAMENTO ---
st.sidebar.header("Carica PDF")
u_file = st.sidebar.file_uploader("Scegli file", type="pdf")
if st.sidebar.button("Invia all'IA"):
    if u_file:
        try:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            r = requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, timeout=30)
            if r.status_code == 200:
                st.sidebar.success("Caricato!")
                st.rerun()
            else:
                st.sidebar.error(f"Errore server: {r.status_code}")
        except Exception as e:
            st.sidebar.error(f"Errore: {e}")

# --- TABELLA E DETTAGLI ---
if dati_json:
    df = pd.DataFrame(dati_json)
    st.dataframe(df[["id", "stato", "data_caricamento"]], use_container_width=True)
    
    st.divider()
    id_scelto = st.selectbox("Seleziona ID", [f["id"] for f in dati_json])
    
    if id_scelto:
        s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_scelto}/scheda")
        if s_res.status_code == 200:
            scheda = s_res.json()
            col1, col2 = st.columns(2)
            with col1:
                st.info("### Dati IA")
                st.write(f"**Organo:** {scheda.get('organo_ai')}")
                st.write(f"**Massima:** {scheda.get('massima_ai')}")
            with col2:
                st.success("### Validazione")
                v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                v_max = st.text_area("Massima", value=scheda.get('massima_ai'), height=200)
                if st.button("SALVA"):
                    p = {"organo": v_org, "massima": v_max}
                    requests.patch(f"{API_URL}/v1/fascicoli/{id_scelto}/validate", json=p)
                    st.success("Salvato!")
                    st.rerun()
else:
    st.info("Nessun documento trovato. Carica un file.")
