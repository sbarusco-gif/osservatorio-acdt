import streamlit as st
import requests
import pandas as pd
import os

# --- CONFIGURAZIONE DINAMICA ---
# Se il software gira sul Web (Render), userà l'URL del backend salvato nelle impostazioni.
# Se gira sul tuo PC, userà l'indirizzo locale 127.0.0.1
BACKEND_URL_ENV = os.getenv("BACKEND_URL", "http://127.0.0.1:9999")
API_URL = BACKEND_URL_ENV.strip("/") # Rimuove eventuali barre finali

# Configurazione Pagina
st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# --- SIDEBAR: CARICAMENTO ---
st.sidebar.header("📥 Caricamento Sentenza")
u_file = st.sidebar.file_uploader("Seleziona il PDF della sentenza", type="pdf")

if st.sidebar.button("Invia all'IA"):
    if u_file:
        try:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            with st.sidebar.status("Invio in corso..."):
                r = requests.post(f"{API_URL}/v1/fascicoli/upload", files=files)
            if r.status_code == 200:
                st.sidebar.success("File caricato! Attendi l'analisi e ricarica.")
                st.rerun()
            else:
                st.sidebar.error(f"Errore server: {r.status_code}")
        except Exception as e:
            st.sidebar.error(f"Errore di connessione: {e}")
    else:
        st.sidebar.error("Seleziona prima un file!")

# --- RECUPERO DATI DAL DATABASE ---
try:
    res = requests.get(f"{API_URL}/v1/fascicoli")
    if res.status_code == 200:
        dati_json = res.json()
    else:
        dati_json = []
except Exception as e:
    st.error(f"⚠️ Impossibile connettersi al Backend all'indirizzo: {API_URL}")
    st.info("Controlla le variabili d'ambiente su Render (BACKEND_URL).")
    dati_json = []

# --- INTERFACCIA PRINCIPALE ---
if not dati_json:
    st.info("👋 Benvenuto! Al momento non ci sono documenti nel database. Carica il primo PDF dalla barra laterale.")
else:
    # Mostra la tabella dei fascicoli
    df = pd.DataFrame(dati_json)
    st.subheader(f"Elenco Documenti ({len(dati_json)})")
    # Nota: su versioni recenti di Streamlit 'use_container_width' è preferibile
    st.dataframe(df[["id", "stato", "data_caricamento"]], use_container_width=True)

    st.divider()

    # --- SEZIONE REVISIONE ---
    st.subheader("🔍 Revisione e Validazione")
    
    # Selezione tramite ID
    opzioni_id = [f["id"] for f in dati_json]
    id_scelto = st.selectbox("Seleziona l'ID del fascicolo per vedere i dettagli", opzioni_id)

    if id_scelto:
        # Troviamo il percorso del file per il pulsante visualizza
        fascicolo_info = next(f for f in dati_json if f["id"] == id_scelto)
        nome_file_fisico = os.path.basename(fascicolo_info['file_originale'])
        url_pdf = f"{API_URL}/storage/{nome_file_fisico}"

        # Recuperiamo la scheda dal server
        s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_scelto}/scheda")
        
        if s_res.status_code == 200:
            scheda = s_res.json()
            
            if not scheda:
                st.warning("⏳ L'IA sta ancora analizzando il documento. Attendi qualche istante e rinfresca la pagina.")
            else:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.info("### 🤖 Dati estratti dall'IA")
                    st.link_button("📄 VISUALIZZA PDF ORIGINALE", url_pdf)
                    
                    st.write(f"**Organo Suggerito:** {scheda.get('organo_ai', 'N/D')}")
                    st.write(f"**Numero Suggerito:** {scheda.get('numero_sentenza_ai', 'N/D')}")
                    st.write("**Descrizione / Massima (Bozza AI):**")
                    st.markdown(f"> {scheda.get('massima_ai', 'Analisi in corso...')}")
                
                with col2:
                    st.success("### ✅ Validazione Ufficiale")
                    v_org = st.text_input("Conferma Organo", value=scheda.get('organo_ai') or "")
                    v_num = st.text_input("Conferma Numero", value=scheda.get('numero_sentenza_ai') or "")
                    v_max = st.text_area("Revisione Massima / Descrizione", value=scheda.get('massima_ai') or "", height=300)
                    
                    if st.button("SALVA E RINOMINA FILE"):
                        payload = {
                            "organo": v_org,
                            "numero_sentenza": v_num,
                            "massima": v_max
                        }
                        try:
                            v_res = requests.patch(f"{API_URL}/v1/fascicoli/{id_scelto}/validate", json=payload)
                            if v_res.status_code == 200:
                                st.balloons()
                                st.success("Documento validato e file rinominato correttamente!")
                                st.rerun()
                            else:
                                st.error(f"Errore nella validazione: {v_res.text}")
                        except Exception as e:
                            st.error(f"Errore tecnico: {e}")
        else:
            st.error("Impossibile recuperare i dettagli della scheda AI.")
