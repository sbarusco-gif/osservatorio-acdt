import streamlit as st
import requests
import os
import time

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="ACDT AI - Osservatorio", layout="wide", page_icon="⚖️")

# Recupero dinamico dell'URL del backend
DEFAULT_API = "https://osservatorio-dashboard.onrender.com"
API_URL = os.getenv("BACKEND_URL", DEFAULT_API).strip("/")

def call_api(method, endpoint, params=None, json=None, files=None):
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    try:
        if method == "GET": r = requests.get(url, params=params, timeout=15)
        elif method == "POST": r = requests.post(url, json=json, files=files, timeout=60)
        elif method == "PATCH": r = requests.patch(url, json=json, timeout=15)
        elif method == "DELETE": r = requests.delete(url, timeout=15)
        
        if r.status_code == 200: return r.json()
        st.error(f"Errore {r.status_code}: {r.text}")
    except Exception as e:
        st.warning(f"Connessione fallita verso {url}. Errore: {e}")
    return None

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

t_gest, t_ricerca, t_arch = st.tabs(["📋 Gestione", "🔍 Ricerca AI", "📚 Archivio"])

# --- GESTIONE ---
with t_gest:
    with st.sidebar:
        st.header("Nuovo Caricamento")
        u_file = st.file_uploader("Carica Sentenza (PDF)", type="pdf")
        if st.button("🚀 ANALIZZA CON IA"):
            if u_file:
                with st.spinner("L'IA sta leggendo la sentenza..."):
                    files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
                    if call_api("POST", "/v1/fascicoli/upload", files=files):
                        st.success("Analisi completata!")
                        st.rerun()
            else: st.warning("Seleziona un file.")

    st.subheader("Fascicoli in Revisione")
    dati = call_api("GET", "/v1/fascicoli")
    if dati:
        da_v = [f for f in dati if f.get('stato') != 'Validato']
        if da_v:
            id_sel = st.selectbox("Seleziona fascicolo", [f["id"] for f in da_v])
            sch = call_api("GET", f"/v1/fascicoli/{id_sel}/scheda")
            if sch:
                c1, c2 = st.columns(2)
                with c1:
                    st.info("🤖 Bozza generata dall'IA")
                    st.markdown(f"**Organo:** {sch.get('organo_ai')}")
                    st.markdown(f"**Numero:** {sch.get('numero_sentenza_ai')}")
                    st.text_area("Massima IA (Sola lettura)", sch.get('massima_ai'), height=350)
                with c2:
                    st.success("✅ Revisione e Pubblicazione")
                    v_org = st.text_input("Organo Corretto", sch.get('organo_ai'))
                    v_num = st.text_input("Numero Corretto", sch.get('numero_sentenza_ai'))
                    v_max = st.text_area("Massima Definitiva", sch.get('massima_ai'), height=350)
                    if st.button("APPROVA E PUBBLICA IN ARCHIVIO"):
                        payload = {"organo": v_org, "numero": v_num, "massima": v_max}
                        if call_api("PATCH", f"/v1/fascicoli/{id_sel}/validate", json=payload):
                            st.success("Pubblicato!")
                            time.sleep(1)
                            st.rerun()
        else: st.info("Nessun documento da validare.")
    else: st.write("In attesa di dati dal server...")

# --- RICERCA AI ---
with t_ricerca:
    q = st.text_input("Inserisci un quesito giuridico...")
    if q:
        r = call_api("GET", "/v1/ricerca/ai", params={"domanda": q})
        if r:
            for res in r:
                with st.expander(f"⚖️ {res['organo_corrente']} - {res['numero_sentenza_corrente']}"):
                    st.write(res['massima_corrente'])

# --- ARCHIVIO ---
with t_arch:
    col_a, col_b = st.columns([0.8, 0.2])
    col_a.subheader("Archivio Storico")
    if col_b.button("🗑️ SVUOTA TUTTO"):
        if call_api("DELETE", "/v1/archivio/clear"):
            st.success("Archivio svuotato!")
            st.rerun()

    arch = call_api("GET", "/v1/archivio")
    if arch:
        for i in arch:
            with st.container(border=True):
                c1, c2 = st.columns([0.8, 0.2])
                c1.markdown(f"**{i.get('organo')} - n. {i.get('numero')}**")
                c1.write(i.get('massima'))
                if i.get('file_url'):
                    # Correzione Link PDF
                    full_url = f"{API_URL}/{i['file_url'].lstrip('/')}"
                    c2.link_button("📄 PDF", full_url)
