import streamlit as st
import requests
import pandas as pd
import os

API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:10000").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="ACDT Osservatorio", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

def safe_get(endpoint, params=None):
    try:
        r = requests.get(f"{API_URL}{endpoint}", params=params, headers=HEADERS, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

t_gest, t_arch = st.tabs(["📋 Gestione e Validazione", "📚 Archivio Massime"])

with t_gest:
    u_file = st.sidebar.file_uploader("Carica PDF", type="pdf")
    if st.sidebar.button("Avvia Analisi"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.success("Caricato!")

    dati = safe_get("/v1/fascicoli")
    if dati:
        da_v = [f for f in dati if f['stato'] != 'Validato']
        if da_v:
            id_sel = st.selectbox("Seleziona ID", [f["id"] for f in da_v])
            scheda = safe_get(f"/v1/fascicoli/{id_sel}/scheda")
            if scheda:
                c1, c2 = st.columns(2)
                with c1:
                    st.info("### 🤖 Suggerimento IA")
                    st.write(f"**Corte:** {scheda.get('organo_ai')}")
                    st.write(f"**Numero:** {scheda.get('numero_sentenza_ai')}")
                    st.markdown(f"> {scheda.get('massima_ai')}")
                with c2:
                    st.success("### ✅ Validazione")
                    v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                    v_num = st.text_input("Numero", value=scheda.get('numero_sentenza_ai'))
                    v_max = st.text_area("Massima Tecnica", value=scheda.get('massima_ai'), height=300)
                    if st.button("APPROVA"):
                        p = {"organo": v_org, "numero": v_num, "massima": v_max}
                        requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=p, headers=HEADERS)
                        st.rerun()

with t_arch:
    st.header("📚 Archivio")
    archivio = safe_get("/v1/archivio")
    if archivio:
        for item in archivio:
            col_t, col_l = st.columns([0.8, 0.2])
            with col_t:
                st.subheader(f"{item.get('organo')} - {item.get('numero')}")
                st.write(item.get('massima'))
            with col_l:
                # USA GET PER EVITARE IL CRASH SE LA CHIAVE MANCA
                url = item.get('file_url')
                if url: st.link_button("📄 PDF", f"{API_URL}{url}")
            st.divider()
