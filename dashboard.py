import streamlit as st
import requests
import pandas as pd
import os

API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:10000").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="ACDT AI", layout="wide")

st.title("⚖️ Osservatorio ACDT")

# Verifica se il Backend è sveglio
try:
    requests.get(f"{API_URL}/", timeout=5)
    backend_live = True
except:
    backend_live = False

if not backend_live:
    st.warning("Il server si sta svegliando... attendi 30 secondi e ricarica la pagina.")
    st.stop()

t_gest, t_ricerca, t_arch = st.tabs(["📋 Gestione", "🔍 Ricerca AI", "📚 Archivio"])

with t_gest:
    u_file = st.sidebar.file_uploader("Carica PDF", type="pdf")
    if st.sidebar.button("Invia all'IA"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.rerun()

    res = requests.get(f"{API_URL}/v1/fascicoli", headers=HEADERS)
    dati = res.json() if res.status_code == 200 else []
    da_v = [f for f in dati if f['stato'] != 'Validato']
    
    if not da_v: st.info("Nessun documento da validare.")
    else:
        id_sel = st.selectbox("Seleziona ID", [f["id"] for f in da_v])
        s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_sel}/scheda", headers=HEADERS)
        if s_res.status_code == 200:
            scheda = s_res.json()
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Organo IA:** {scheda.get('organo_ai')}")
                st.markdown(f"> {scheda.get('massima_ai')}")
            with c2:
                v_org = st.text_input("Organo", value=scheda.get('organo_ai'))
                v_num = st.text_input("Numero", value=scheda.get('numero_sentenza_ai'))
                v_max = st.text_area("Massima", value=scheda.get('massima_ai'), height=250)
                if st.button("APPROVA"):
                    p = {"organo": v_org, "numero": v_num, "massima": v_max}
                    requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=p, headers=HEADERS)
                    st.rerun()

with t_ricerca:
    domanda = st.text_input("Cosa cerchi?")
    if domanda:
        r = requests.get(f"{API_URL}/v1/ricerca/ai", params={"domanda": domanda}, headers=HEADERS)
        for res in r.json():
            with st.expander(f"{res['organo_corrente']} - {res['numero_sentenza_corrente']}"):
                st.write(res['massima_corrente'])

with t_arch:
    arch = requests.get(f"{API_URL}/v1/archivio", headers=HEADERS).json()
    for item in arch:
        st.subheader(f"{item['organo']} - {item['numero']}")
        st.write(item['massima'])
        st.divider()
