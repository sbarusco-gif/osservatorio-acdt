import streamlit as st
import requests
import pandas as pd
import os
import re

# Configurazione URL (Render)
BACKEND_URL_ENV = os.getenv("BACKEND_URL", "http://127.0.0.1:10000")
API_URL = BACKEND_URL_ENV.strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

t_gest, t_ricerca, t_arch = st.tabs(["📋 Gestione e Validazione", "🔍 Ricerca Concettuale AI", "📚 Archivio Massime"])

# --- TAB 1: GESTIONE ---
with t_gest:
    st.sidebar.header("Carica PDF")
    u_file = st.sidebar.file_uploader("Seleziona sentenza", type="pdf")
    if st.sidebar.button("Invia all'IA"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.sidebar.success("Analisi avviata!")
            st.rerun()

    res = requests.get(f"{API_URL}/v1/fascicoli", headers=HEADERS)
    dati = res.json() if res.status_code == 200 else []
    da_v = [f for f in dati if f['stato'] != 'Validato']
    
    if not da_v: st.info("Tutti i documenti sono stati validati.")
    else:
        st.dataframe(pd.DataFrame(da_v)[["id", "stato", "data_caricamento"]], use_container_width=True)
        id_sel = st.selectbox("ID da revisionare", [f["id"] for f in da_v])
        if id_sel:
            s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_sel}/scheda", headers=HEADERS)
            if s_res.status_code == 200:
                scheda = s_res.json()
                c1, c2 = st.columns(2)
                with c1:
                    st.info("### 🤖 Proposta AI")
                    st.write(f"**Organo:** {scheda.get('organo_ai')}")
                    st.markdown(f"> {scheda.get('massima_ai')}")
                with c2:
                    st.success("### ✅ Validazione")
                    v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                    v_num = st.text_input("Numero", value=scheda.get('numero_sentenza_ai'))
                    v_dat = st.text_input("Data (GG-MM-AAAA)")
                    v_max = st.text_area("Massima", value=scheda.get('massima_ai'), height=300)
                    if st.button("APPROVA E RINOMINA"):
                        p = {"organo": v_org, "numero": v_num, "massima": v_max, "note_riservate": v_dat}
                        requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=p, headers=HEADERS)
                        st.balloons()
                        st.rerun()

# --- TAB 2: RICERCA AI ---
with t_ricerca:
    st.header("🔍 Ricerca Intelligente AI")
    st.write("Fai una domanda all'archivio (es: 'Quali sono i vizi di notifica più comuni?')")
    domanda = st.text_input("Cosa stai cercando?")
    if domanda:
        with st.spinner("L'IA sta consultando le massime validate..."):
            r = requests.get(f"{API_URL}/v1/ricerca/ai", params={"domanda": domanda}, headers=HEADERS)
            if r.status_code == 200:
                risultati = r.json()
                if non risultati: st.warning("Nessun precedente trovato.")
                for res in risultati:
                    with st.expander(f"⚖️ {res['organo_corrente']} - Sent. {res['numero_sentenza_corrente']}"):
                        st.write(res['massima_corrente'])

# --- TAB 3: ARCHIVIO ---
with t_arch:
    st.header("📚 Archivio Storico")
    arch = requests.get(f"{API_URL}/v1/archivio", headers=HEADERS).json()
    for item in arch:
        c_t, c_l = st.columns([0.8, 0.2])
        with c_t:
            st.subheader(f"📌 {item['organo']} - {item['numero']}")
            st.write(item['massima'])
        with c_l:
            st.link_button("📄 Vedi PDF", f"{API_URL}{item['file_url']}")
        st.divider()
