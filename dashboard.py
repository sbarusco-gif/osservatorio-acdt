import streamlit as st
import requests
import pandas as pd
import os

API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:10000").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.set_page_config(page_title="ACDT AI", layout="wide", page_icon="⚖️")
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

def safe_req(method, endpoint, **kwargs):
    try:
        url = f"{API_URL}{endpoint}"
        if method == "GET": r = requests.get(url, headers=HEADERS, timeout=15, **kwargs)
        elif method == "POST": r = requests.post(url, headers=HEADERS, timeout=30, **kwargs)
        elif method == "PATCH": r = requests.patch(url, headers=HEADERS, timeout=15, **kwargs)
        return r.json() if r.status_code == 200 else None
    except: return None

t_gest, t_ricerca, t_arch = st.tabs(["📋 Gestione", "🔍 Ricerca AI", "📚 Archivio"])

with t_gest:
    u_file = st.sidebar.file_uploader("Carica PDF", type="pdf")
    if st.sidebar.button("Invia all'IA"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.rerun()

    dati = safe_req("GET", "/v1/fascicoli")
    if dati:
        da_v = [f for f in dati if f['stato'] != 'Validato']
        if da_v:
            id_sel = st.selectbox("Seleziona ID", [f["id"] for f in da_v])
            scheda = safe_req("GET", f"/v1/fascicoli/{id_sel}/scheda")
            if scheda:
                c1, c2 = st.columns(2)
                with c1:
                    st.info("### 🤖 Bozza AI")
                    st.write(f"**Corte:** {scheda.get('organo_ai')}")
                    st.write(f"**Numero:** {scheda.get('numero_sentenza_ai')}")
                    st.markdown(f"> {scheda.get('massima_ai')}")
                with c2:
                    st.success("### ✅ Revisione")
                    v_org = st.text_input("Organo", value=scheda.get('organo_ai') or "")
                    v_num = st.text_input("Numero", value=scheda.get('numero_sentenza_ai') or "")
                    v_dat = st.text_input("Data (GG-MM-AAAA)")
                    v_max = st.text_area("Massima", value=scheda.get('massima_ai') or "", height=250)
                    if st.button("APPROVA"):
                        p = {"organo": v_org, "numero": v_num, "massima": v_max, "note_riservate": v_dat}
                        safe_req("PATCH", f"/v1/fascicoli/{id_sel}/validate", json=p)
                        st.rerun()
        else: st.info("Tutto validato.")
    else: st.warning("In attesa del server...")

with t_ricerca:
    q = st.text_input("Cosa cerchi?")
    if q:
        r = safe_req("GET", "/v1/ricerca/ai", params={"domanda": q})
        if r:
            for res in r:
                with st.expander(f"{res['organo_corrente']} - {res['numero_sentenza_corrente']}"):
                    st.write(res['massima_corrente'])

with t_arch:
    arch = safe_req("GET", "/v1/archivio")
    if arch:
        for i in arch:
            col_t, col_l = st.columns([0.8, 0.2])
            with col_t:
                st.subheader(f"{i.get('organo')} - {i.get('numero')}")
                st.write(i.get('massima'))
            with col_l:
                if i.get('file_url'): st.link_button("📄 PDF", f"{API_URL}{i['file_url']}")
            st.divider()
