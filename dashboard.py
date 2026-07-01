import streamlit as st
import requests
import pandas as pd
import os

# --- CONFIGURAZIONE URL ---
# Usiamo una logica robusta: se BACKEND_URL è impostato su Render, usa quello.
# Altrimenti usa quello del tuo PC.
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:9999")
API_URL = BACKEND_URL.strip("/")

st.set_page_config(page_title="Osservatorio ACDT", layout="wide")

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# --- RECUPERO DATI ---
try:
    res = requests.get(f"{API_URL}/v1/fascicoli", timeout=10)
    dati_json = res.json() if res.status_code == 200 else []
except Exception as e:
    st.error(f"Errore di collegamento al server: {e}")
    dati_json = []

# --- SIDEBAR ---
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

# --- MAIN UI ---
if not dati_json:
    st.info("In attesa di documenti...")
else:
    df = pd.DataFrame(dati_json)
    st.dataframe(df[["id", "stato", "data_caricamento"]], use_container_width=True)
    
    st.divider()
    
    id_list = [f["id"] for f in dati_json]
    id_scelto = st.selectbox("Seleziona ID", id_list)
    
    if id_scelto:
        try:
            s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_scelto}/scheda", timeout=10)
            if s_res.status_code == 200:
                scheda = s_res.json()
                col1, col2 = st.columns(2)
                with col1:
                    st.info("### Dati IA")
                    st.write(f"**Organo:** {scheda.get('organo_ai', 'N/D')}")
                    st.write(f"**Massima:** {scheda.get('massima_ai', 'N/D')}")
                with col2:
                    st.success("### Validazione")
                    v_org = st.text_input("Organo", value=scheda.get('organo_ai', ''))
                    v_max = st.text_area("Massima", value=scheda.get('massima_ai', ''), height=200)
                    if st.button("SALVA"):
                        payload = {"organo": v_org, "massima": v_max}
                        requests.patch(f"{API_URL}/v1/fascicoli/{id_scelto}/validate", json=payload, timeout=10)
                        st.success("Salvato!")
                        st.rerun()
        except Exception as e:
            st.error(f"Errore nel recupero della scheda: {e}")
