import streamlit as st
import requests
import os
import time

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="ACDT AI - Osservatorio", layout="wide", page_icon="⚖️")

# Recupero dinamico dell'URL del backend
# Se sei su Render, imposta BACKEND_URL nelle Environment Variables con l'indirizzo della tua app
DEFAULT_API = "https://osservatorio-dashboard.onrender.com"
API_URL = os.getenv("BACKEND_URL", DEFAULT_API).strip("/")
HEADERS = {"User-Agent": "ACDT-Dashboard/1.0"}

# --- FUNZIONE LOGICA API (POTENZIATA) ---
def call_api(method, endpoint, params=None, json=None, files=None, timeout=20):
    url = f"{API_URL}{endpoint}"
    try:
        if method == "GET":
            r = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        elif method == "POST":
            r = requests.post(url, headers=HEADERS, json=json, files=files, timeout=timeout)
        elif method == "PATCH":
            r = requests.patch(url, headers=HEADERS, json=json, timeout=timeout)
        
        if r.status_code == 200:
            return r.json()
        else:
            st.error(f"❌ Errore Server ({r.status_code}): {r.text}")
            return None
    except requests.exceptions.ConnectionError:
        st.warning(f"⚠️ Impossibile connettersi al server all'indirizzo: {API_URL}")
        return "CONNECTION_ERROR"
    except Exception as e:
        st.error(f"💥 Errore imprevisto: {e}")
        return None

# --- UI PRINCIPALE ---
st.title("⚖️ Osservatorio Giurisprudenza Tributaria")
st.caption(f"Connesso a: {API_URL}")

t_gest, t_ricerca, t_arch = st.tabs(["📋 Gestione Fascicoli", "🔍 Ricerca AI", "📚 Archivio Storico"])

# --- TAB 1: GESTIONE ---
with t_gest:
    st.sidebar.header("Caricamento Documenti")
    u_file = st.sidebar.file_uploader("Trascina qui il PDF della sentenza", type="pdf")
    
    if st.sidebar.button("🚀 Elabora con AI"):
        if u_file:
            with st.spinner("L'intelligenza artificiale sta analizzando il documento..."):
                files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
                res = call_api("POST", "/v1/fascicoli/upload", files=files)
                if res:
                    st.sidebar.success("Documento inviato con successo!")
                    time.sleep(2)
                    st.rerun()
        else:
            st.sidebar.warning("Seleziona un file prima di inviare.")

    st.subheader("Fascicoli in attesa di revisione")
    dati = call_api("GET", "/v1/fascicoli")

    if dati == "CONNECTION_ERROR":
        st.info("🔄 Tentativo di riconnessione in corso... Verifica che il backend sia attivo.")
    elif dati:
        da_validare = [f for f in dati if f.get('stato') != 'Validato']
        
        if da_validare:
            id_sel = st.selectbox("Seleziona fascicolo da revisionare", 
                                  options=[f["id"] for f in da_validare],
                                  format_func=lambda x: f"Fascicolo ID: {x}")
            
            scheda = call_api("GET", f"/v1/fascicoli/{id_sel}/scheda")
            
            if scheda:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("### 🤖 Suggerimento AI")
                    st.info(f"**Organo:** {scheda.get('organo_ai', 'N/D')}\n\n"
                            f"**Sentenza n.:** {scheda.get('numero_sentenza_ai', 'N/D')}\n\n"
                            f"**Massima proposta:**\n\n{scheda.get('massima_ai', 'Generazione in corso...')}")
                
                with col2:
                    st.markdown("### ✅ Validazione Umana")
                    v_org = st.text_input("Organo Giudicante", value=scheda.get('organo_ai') or "")
                    v_num = st.text_input("Numero Sentenza", value=scheda.get('numero_sentenza_ai') or "")
                    v_dat = st.text_input("Data Deposito (es. 01/01/2024)", value=scheda.get('note_riservate') or "")
                    v_max = st.text_area("Massima Definitiva", value=scheda.get('massima_ai') or "", height=300)
                    
                    if st.button("CONFERMA E PUBBLICA", use_container_width=True):
                        payload = {"organo": v_org, "numero": v_num, "massima": v_max, "note_riservate": v_dat}
                        if call_api("PATCH", f"/v1/fascicoli/{id_sel}/validate", json=payload):
                            st.success("Sentenza pubblicata in archivio!")
                            time.sleep(1)
                            st.rerun()
        else:
            st.success("✅ Ottimo lavoro! Tutti i fascicoli sono stati revisionati.")
    else:
        st.write("Nessun fascicolo da mostrare.")

# --- TAB 2: RICERCA AI ---
with t_ricerca:
    st.subheader("Chiedi all'intelligenza artificiale")
    domanda = st.text_input("Inserisci un quesito giuridico (es: Orientamento Cassazione su IMU prima casa)")
    
    if domanda:
        with st.spinner("Ricerca nei precedenti in corso..."):
            risultati = call_api("GET", "/v1/ricerca/ai", params={"domanda": domanda})
            if risultati:
                for r in risultati:
                    with st.expander(f"⚖️ {r.get('organo_corrente')} - n. {r.get('numero_sentenza_corrente')}"):
                        st.markdown(f"**Massima:**\n{r.get('massima_corrente')}")
                        if r.get('punteggio'):
                            st.caption(f"Rilevanza: {round(r['punteggio']*100)}%")

# --- TAB 3: ARCHIVIO ---
with t_arch:
    st.subheader("Sentenze Validate")
    archivio = call_api("GET", "/v1/archivio")
    if archivio:
        for item in archivio:
            with st.container():
                c1, c2 = st.columns([0.85, 0.15])
                with c1:
                    st.markdown(f"### {item.get('organo')} - {item.get('numero')}")
                    st.write(item.get('massima'))
                with c2:
                    if item.get('file_url'):
                        st.link_button("📂 PDF", f"{API_URL}{item['file_url']}")
                st.divider()
