import streamlit as st
import requests
import pandas as pd
import os
import re

API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:10000").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="ACDT Osservatorio", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

t_gest, t_ricerca, t_arch = st.tabs(["📋 Gestione", "🔍 Ricerca AI", "📚 Archivio Massime"])

# --- TAB 1: GESTIONE ---
with t_gest:
    st.sidebar.header("Carica PDF")
    u_file = st.sidebar.file_uploader("Trascina sentenza", type="pdf")
    if st.sidebar.button("Invia all'IA"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.rerun()

    res = requests.get(f"{API_URL}/v1/fascicoli", headers=HEADERS)
    dati = res.json() if res.status_code == 200 else []
    da_v = [f for f in dati if f['stato'] != 'Validato']
    
    if not da_v: st.info("Nessun documento in attesa.")
    else:
        id_sel = st.selectbox("Seleziona ID da validare", [f["id"] for f in da_v])
        s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_sel}/scheda", headers=HEADERS)
        if s_res.status_code == 200:
            scheda = s_res.json()
            c1, c2 = st.columns(2)
            with c1:
                st.info("### 🤖 Bozza AI")
                st.write(f"**Corte:** {scheda.get('organo_ai')}")
                st.write(f"**Numero:** {scheda.get('numero_sentenza_ai')}")
                st.markdown(f"> {scheda.get('massima_ai')}")
            with c2:
                st.success("### ✅ Revisione Umana")
                v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                v_num = st.text_input("Numero", value=scheda.get('numero_sentenza_ai'))
                v_dat = st.text_input("Data (GG-MM-AAAA)")
                v_max = st.text_area("Massima Tecnica", value=scheda.get('massima_ai'), height=250)
                if st.button("APPROVA E RINOMINA"):
                    p = {"organo": v_org, "numero": v_num, "massima": v_max, "note_riservate": v_dat}
                    requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=p, headers=HEADERS)
                    st.rerun()

# --- TAB 2: RICERCA AI ---
with t_ricerca:
    st.header("🔍 Ricerca Intelligente")
    q = st.text_input("Cosa stai cercando? (es: residenza coniugi IMU)")
    if q:
        r_ai = requests.get(f"{API_URL}/v1/ricerca/ai", params={"domanda": q}, headers=HEADERS)
        for r in r_ai.json():
            with st.expander(f"{r['organo_corrente']} - Sent. {r['numero_sentenza_corrente']}"):
                st.write(r['massima_corrente'])

# --- TAB 3: ARCHIVIO ---
with t_arch:
    st.header("📚 Repertorio Massime")
    arch = requests.get(f"{API_URL}/v1/archivio", headers=HEADERS).json()
    for item in arch:
        col_t, col_l = st.columns([0.8, 0.2])
        with col_t:
            st.subheader(f"{item['organo']} - {item['numero']}")
            st.write(item['massima'])
        with col_l:
            st.link_button("📄 PDF", f"{API_URL}{item['file_url']}")
        st.divider()
