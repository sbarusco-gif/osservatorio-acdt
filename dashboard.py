import streamlit as st
import requests
import pandas as pd
import os
import re

# --- CONFIGURAZIONE ---
# Recupera l'URL del backend dalle impostazioni di Render o usa localhost come fallback
API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:10000").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# --- DIVISIONE IN SCHEDE (TABS) ---
tab_gestione, tab_ricerca, tab_archivio = st.tabs([
    "📋 Gestione e Validazione", 
    "🔍 Ricerca Rapida", 
    "📚 Archivio Massime"
])

# --- SCHEDA 1: GESTIONE (Caricamento e Revisione AI) ---
with tab_gestione:
    st.sidebar.header("📥 Caricamento")
    u_file = st.sidebar.file_uploader("Trascina qui il PDF della sentenza", type="pdf")
    if st.sidebar.button("Invia all'IA per Analisi"):
        if u_file:
            try:
                files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
                r = requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
                if r.status_code == 200:
                    st.sidebar.success("File caricato! L'IA sta lavorando...")
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
        st.info("Nessun documento presente. Carica un PDF dalla barra laterale.")
    else:
        # Filtriamo quelli da validare
        da_validare = [f for f in tutti_i_dati if f['stato'] != 'Validato']
        
        if not da_validare:
            st.success("✅ Tutti i documenti sono stati validati e archiviati!")
        else:
            st.subheader("Documenti in attesa di revisione")
            df_v = pd.DataFrame(da_validare)
            st.dataframe(df_v[["id", "stato", "data_caricamento"]], use_container_width=True)
            
            st.divider()
            id_sel = st.selectbox("Seleziona ID per validare la massima tecnica", [f["id"] for f in da_validare])
            
            if id_sel:
                s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_sel}/scheda", headers=HEADERS)
                if s_res.status_code == 200:
                    scheda = s_res.json()
                    
                    # Estrazione data dalle note AI (formato GG-MM-AAAA)
                    note_ia = scheda.get('note_riservate', '')
                    data_match = re.search(r'\d{2}-\d{2}-\d{4}', note_ia)
                    data_suggerita = data_match.group() if data_match else ""

                    col1, col2 = st.columns(2)
                    with col1:
                        st.info("### 🤖 Suggerimenti dell'IA")
                        st.write(f"**Organo:** {scheda.get('organo_ai')}")
                        st.write(f"**Numero:** {scheda.get('numero_sentenza_ai')}")
                        st.write(f"**Data rilevata:** {data_suggerita}")
                        st.write("**Massima Tecnica proposta:**")
                        st.markdown(f"> {scheda.get('massima_ai')}")
                    
                    with col2:
                        st.success("### ✅ Validazione Ufficiale")
                        v_org = st.text_input("Conferma Organo", value=scheda.get('organo_ai'))
                        v_num = st.text_input("Conferma Numero", value=scheda.get('numero_sentenza_ai'))
                        v_dat = st.text_input("Conferma Data (GG-MM-AAAA)", value=data_suggerita)
                        v_max = st.text_area("Massima Tecnica Definitiva", value=scheda.get('massima_ai'), height=300)
                        
                        if st.button("SALVA, RINOMINA E ARCHIVIA"):
                            payload = {
                                "organo": v_org,
                                "numero_sentenza": v_num,
                                "massima": v_max,
                                "note_riservate": v_dat # Usiamo questo campo per passare la data al backend
                            }
                            v_res = requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=payload, headers=HEADERS)
                            if v_res.status_code == 200:
                                st.balloons()
                                st.success("Sentenza archiviata con successo!")
                                st.rerun()

# --- SCHEDA 2: RICERCA (Consultazione Rapida) ---
with tab_ricerca:
    st.header("🔍 Ricerca nell'Osservatorio")
    q = st.text_input("Cerca per parola chiave, articolo di legge o organo...")
    if q:
        r_res = requests.get(f"{API_URL}/v1/ricerca", params={"query": q}, headers=HEADERS)
        if r_res.status_code == 200:
            risultati = r_res.json()
            st.write(f"Trovate {len(risultati)} massime corrispondenti.")
            for r in risultati:
                with st.expander(f"📌 {r['organo_corrente']} n. {r['numero_sentenza_corrente']}"):
                    st.write(r['massima_corrente'])

# --- SCHEDA 3: 📚 ARCHIVIO (Il Repertorio Ufficiale) ---
with tab_archivio:
    st.header("📚 Repertorio delle Massime Validate")
    st.write("Elenco ufficiale delle sentenze analizzate e rinominate.")
    
    arch_res = requests.get(f"{API_URL}/v1/archivio", headers=HEADERS)
    if arch_res.status_code == 200:
        archivio = arch_res.json()
        if not archivio:
            st.warning("L'archivio è vuoto. Valida i documenti nella prima scheda.")
        else:
            df_arch = pd.DataFrame(archivio)
            
            # Bottone di esportazione
            csv = df_arch.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Scarica Archivio Excel (CSV)", csv, "archivio_acdt.csv", "text/csv")
            
            st.divider()
            
            for item in archivio:
                c_testo, c_link = st.columns([0.8, 0.2])
                with c_testo:
                    st.subheader(f"⚖️ {item['organo']} - {item['numero']}")
                    st.write(item['massima'])
                with c_link:
                    # Il link punta al file rinominato correttamente dal backend
                    st.link_button("📄 Apri PDF", f"{API_URL}{item['file_url']}")
                st.divider()
