import streamlit as st
import requests
import pandas as pd
import os

# Configurazione della pagina
st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")

# Indirizzo del server Backend (assicurati che main.py giri sulla porta 9999)
API_URL = "http://127.0.0.1:9999"

st.title("⚖️ Osservatorio ACDT - Revisione Sentenze")

# --- RECUPERO DATI DAL DATABASE ---
try:
    res = requests.get(f"{API_URL}/v1/fascicoli")
    dati_json = res.json() if res.status_code == 200 else []
except:
    dati_json = []

# --- SIDEBAR: CARICAMENTO NUOVI FILE ---
st.sidebar.header("Nuovo File")
u_file = st.sidebar.file_uploader("Carica un PDF della sentenza", type="pdf")
if st.sidebar.button("Invia all'IA"):
    if u_file:
        files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
        requests.post(f"{API_URL}/v1/fascicoli/upload", files=files)
        st.sidebar.success("File caricato con successo! Ricarica la pagina.")
        st.rerun()
    else:
        st.sidebar.error("Per favore, seleziona un file PDF.")

# --- INTERFACCIA PRINCIPALE ---
if not dati_json:
    st.info("In attesa di documenti nel database... Carica un PDF dalla barra laterale per iniziare.")
else:
    # Mostra tabella riassuntiva dei file caricati
    df = pd.DataFrame(dati_json)
    st.subheader(f"Elenco Fascicoli nel Sistema ({len(dati_json)})")
    st.dataframe(df[["id", "stato", "data_caricamento"]], width=1200)

    st.divider()

    # --- SEZIONE REVISIONE E VALIDAZIONE ---
    st.subheader("🔍 Dettagli Fascicolo e Validazione")
    
    # Menu a tendina per selezionare il fascicolo
    opzioni_id = [f["id"] for f in dati_json]
    id_scelto = st.selectbox("Seleziona un ID Fascicolo per revisionare i dati", opzioni_id)

    if id_scelto:
        # 1. Recupero informazioni sul file per il link al PDF
        fascicolo_scelto = next(f for f in dati_json if f["id"] == id_scelto)
        # Estraiamo solo il nome del file dal percorso salvato nel DB
        nome_file_fisico = os.path.basename(fascicolo_scelto['file_originale'])
        url_pdf = f"{API_URL}/storage/{nome_file_fisico}"

        # 2. Recupero della scheda generata dall'IA
        s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_scelto}/scheda")
        
        if s_res.status_code == 200:
            scheda = s_res.json()
            if scheda:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.info("### 🤖 Dati estratti dall'IA")
                    
                    # PULSANTE PER APRIRE IL PDF IN UNA NUOVA SCHEDA
                    st.link_button("📄 VISUALIZZA PDF ORIGINALE", url_pdf)
                    
                    st.write(f"**Organo Rilevato:** {scheda.get('organo_ai', 'N/D')}")
                    st.write(f"**Numero Sentenza:** {scheda.get('numero_sentenza_ai', 'N/D')}")
                    st.write("**Descrizione / Massima (Bozza AI):**")
                    st.markdown(f"> {scheda.get('massima_ai', 'Testo non rilevato')}")
                
                with col2:
                    st.success("### ✅ Validazione Ufficiale")
                    st.write("Modifica i campi qui sotto e clicca salva per ufficializzare i dati e rinominare il file.")
                    
                    v_org = st.text_input("Organo Ufficiale", value=scheda.get('organo_ai') or "")
                    v_num = st.text_input("Numero Sentenza Ufficiale", value=scheda.get('numero_sentenza_ai') or "")
                    v_max = st.text_area("Descrizione / Massima Definitiva", value=scheda.get('massima_ai') or "", height=350)
                    
                    if st.button("SALVA VALIDAZIONE E RINOMINA FILE"):
                        payload = {
                            "organo": v_org,
                            "numero_sentenza": v_num,
                            "massima": v_max
                        }
                        v_res = requests.patch(f"{API_URL}/v1/fascicoli/{id_scelto}/validate", json=payload)
                        if v_res.status_code == 200:
                            st.balloons()
                            st.success("Validazione completata! Il file è stato rinominato correttamente in archivio.")
                            # Ricarica la pagina per aggiornare i nomi dei file nella tabella
                            st.rerun()
                        else:
                            st.error(f"Errore durante la validazione: {v_res.text}")
            else:
                st.warning("L'IA sta ancora analizzando questo file... Attendi qualche secondo e rinfresca la pagina.")
        else:
            st.error("Non è stato possibile recuperare la scheda per questo fascicolo.")