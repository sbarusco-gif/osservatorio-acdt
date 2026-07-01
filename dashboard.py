import streamlit as st
import requests
import pandas as pd
import os
import re

# --- CONFIGURAZIONE ---
# Recupera l'URL del backend dalle impostazioni di Render
BACKEND_URL_ENV = os.getenv("BACKEND_URL", "http://127.0.0.1:10000")
API_URL = BACKEND_URL_ENV.strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# --- DIVISIONE IN SCHEDE (TABS) ---
tab_gestione, tab_ricerca, tab_archivio = st.tabs([
    "📋 Gestione e Validazione", 
    "🔍 Ricerca Intelligente AI", 
    "📚 Archivio Massime"
])

# --- SCHEDA 1: GESTIONE (Caricamento e Revisione AI) ---
with tab_gestione:
    st.sidebar.header("📥 Caricamento")
    u_file = st.sidebar.file_uploader("Scegli il PDF della sentenza", type="pdf")
    if st.sidebar.button("Invia all'IA per Analisi"):
        if u_file:
            try:
                files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
                with st.spinner("Invio al server..."):
                    r = requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
                if r.status_code == 200:
                    st.sidebar.success("File caricato! L'analisi AI è partita.")
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"Errore: {e}")

    # Recupero fascicoli in lavorazione
    try:
        res = requests.get(f"{API_URL}/v1/fascicoli", headers=HEADERS)
        tutti_i_dati = res.json() if res.status_code == 200 else []
    except:
        tutti_i_dati = []

    if not tutti_i_dati:
        st.info("Benvenuto! Carica un PDF per iniziare l'analisi.")
    else:
        # Filtriamo quelli da validare (stato != 'Validato')
        da_validare = [f for f in tutti_i_dati if f['stato'] != 'Validato']
        
        if not da_validare:
            st.success("✅ Non ci sono nuovi documenti da revisionare.")
        else:
            st.subheader("Documenti pronti per la validazione tecnica")
            df_v = pd.DataFrame(da_validare)
            st.dataframe(df_v[["id", "stato", "data_caricamento"]], use_container_width=True)
            
            st.divider()
            id_sel = st.selectbox("Seleziona ID per revisionare la massima", [f["id"] for f in da_validare])
            
            if id_sel:
                s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_sel}/scheda", headers=HEADERS)
                if s_res.status_code == 200:
                    scheda = s_res.json()
                    
                    # Estrazione data rilevata (formato GG-MM-AAAA)
                    note_ia = scheda.get('note_riservate', '')
                    data_match = re.search(r'\d{2}-\d{2}-\d{4}', note_ia)
                    data_suggerita = data_match.group() if data_match else ""

                    col1, col2 = st.columns(2)
                    with col1:
                        st.info("### 🤖 Proposta AI (Bozza)")
                        st.write(f"**Organo:** {scheda.get('organo_ai')}")
                        st.write(f"**Numero:** {scheda.get('numero_sentenza_ai')}")
                        st.write(f"**Data:** {data_suggerita}")
                        st.markdown("**Massima Tecnica:**")
                        st.markdown(f"> {scheda.get('massima_ai')}")
                        if "Norme:" in note_ia:
                            st.caption(f"Norme rilevate: {note_ia.split('Norme:')[1]}")
                    
                    with col2:
                        st.success("### ✅ Validazione Ufficiale")
                        v_org = st.text_input("Organo Ufficiale", value=scheda.get('organo_ai'))
                        v_num = st.text_input("Numero/Anno", value=scheda.get('numero_sentenza_ai'))
                        v_dat = st.text_input("Data Deposito (GG-MM-AAAA)", value=data_suggerita)
                        v_max = st.text_area("Massima Definitiva", value=scheda.get('massima_ai'), height=300)
                        
                        if st.button("APPROVA, RINOMINA E ARCHIVIA"):
                            payload = {
                                "organo": v_org,
                                "numero_sentenza": v_num,
                                "massima": v_max,
                                "note_riservate": v_dat # Passiamo la data qui
                            }
                            v_res = requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=payload, headers=HEADERS)
                            if v_res.status_code == 200:
                                st.balloons()
                                st.rerun()

# --- SCHEDA 2: RICERCA (Motore Semantico AI) ---
with tab_ricerca:
    st.header("🔍 Ricerca Intelligente con Intelligenza Artificiale")
    st.write("Descrivi un caso legale o un dubbio giuridico. L'IA cercherà il significato delle massime in archivio.")
    
    domanda_ai = st.text_input("Domanda all'Osservatorio", placeholder="Esempio: Casi di nullità della notifica per irreperibilità del destinatario")
    
    if domanda_ai:
        with st.spinner("L'IA sta consultando le massime validate..."):
            try:
                r_ai = requests.get(f"{API_URL}/v1/ricerca/ai", params={"domanda": domanda_ai}, headers=HEADERS)
                if r_ai.status_code == 200:
                    risultati = r_ai.json()
                    if risultati:
                        st.success(f"Ho trovato {len(risultati)} sentenze pertinenti al tuo quesito:")
                        for r in risultati:
                            with st.expander(f"⚖️ {r['organo_corrente']} - Sent. n. {r['numero_sentenza_corrente']}"):
                                st.markdown("**Principio di diritto:**")
                                st.write(r['massima_corrente'])
                                # Link al PDF se disponibile
                                nome_pdf = f"{r['organo_corrente']}_{r['numero_sentenza_corrente']}".replace(" ","_")
                                st.caption("Puoi trovare il file completo nella scheda Archivio.")
                    else:
                        st.warning("Nessun precedente trovato per questo specifico concetto.")
                else:
                    st.error("Il motore di ricerca AI non è al momento disponibile.")
            except Exception as e:
                st.error(f"Errore di connessione: {e}")

# --- SCHEDA 3: 📚 ARCHIVIO (Il Repertorio Ufficiale) ---
with tab_archivio:
    st.header("📚 Repertorio Ufficiale delle Massime")
    
    arch_res = requests.get(f"{API_URL}/v1/archivio", headers=HEADERS)
    if arch_res.status_code == 200:
        archivio = arch_res.json()
        if not archivio:
            st.warning("L'archivio è ancora vuoto. Valida i documenti nella prima scheda.")
        else:
            df_arch = pd.DataFrame(archivio)
            # Bottone Export
            csv = df_arch.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Esporta Archivio in CSV", csv, "archivio_acdt.csv", "text/csv")
            
            st.divider()
            for item in archivio:
                c_testo, c_link = st.columns([0.8, 0.2])
                with c_testo:
                    st.subheader(f"📌 {item['organo']} - {item['numero']}")
                    st.write(item['massima'])
                with c_link:
                    st.link_button("📄 Apri PDF", f"{API_URL}{item['file_url']}")
                st.divider()
