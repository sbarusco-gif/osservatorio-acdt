import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="Osservatorio ACDT", layout="wide", page_icon="⚖️")

API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:9999").strip("/")
HEADERS = {"User-Agent": "Mozilla/5.0"}

st.title("⚖️ Osservatorio Giurisprudenza Tributaria")

# --- DIVISIONE IN 3 SCHEDE ---
tab_gestione, tab_ricerca, tab_archivio = st.tabs([
    "📋 Gestione e Validazione", 
    "🔍 Ricerca Rapida", 
    "📚 Archivio Massime"
])

# --- TAB 1: GESTIONE (Caricamento e Validazione) ---
with tab_gestione:
    st.sidebar.header("📥 Caricamento PDF")
    u_file = st.sidebar.file_uploader("Trascina qui la sentenza", type="pdf")
    if st.sidebar.button("Invia all'IA"):
        if u_file:
            files = {"file": (u_file.name, u_file.getvalue(), "application/pdf")}
            requests.post(f"{API_URL}/v1/fascicoli/upload", files=files, headers=HEADERS)
            st.sidebar.success("Inviato!")
            st.rerun()

    res = requests.get(f"{API_URL}/v1/fascicoli", headers=HEADERS)
    dati = res.json() if res.status_code == 200 else []
    
    if dati:
        df_lavorazione = pd.DataFrame(dati)
        st.subheader("Documenti in fase di analisi/revisione")
        # Filtriamo per mostrare solo quelli NON ancora validati
        df_filtro = df_lavorazione[df_lavorazione['stato'] != 'Validato']
        if not df_filtro.empty:
            st.dataframe(df_filtro[["id", "stato", "data_caricamento"]], use_container_width=True)
            
            id_sel = st.selectbox("Seleziona ID per validare i dati", df_filtro["id"].tolist())
            s_res = requests.get(f"{API_URL}/v1/fascicoli/{id_sel}/scheda", headers=HEADERS)
            if s_res.status_code == 200:
                scheda = s_res.json()
                col1, col2 = st.columns(2)
                with col1:
                    st.info("### 🤖 Proposta AI")
                    st.write(f"**Organo:** {scheda.get('organo_ai')}")
                    st.write(f"**Massima:** {scheda.get('massima_ai')}")
                with col2:
                    st.success("### ✅ Validazione")
                    v_org = st.text_input("Organo Ufficiale", value=scheda.get('organo_ai'))
                    v_num = st.text_input("Numero Sentenza", value=scheda.get('numero_sentenza_ai'))
                    v_max = st.text_area("Massima Ufficiale", value=scheda.get('massima_ai'), height=250)
                    if st.button("APPROVA E ARCHIVIA"):
                        p = {"organo": v_org, "numero_sentenza": v_num, "massima": v_max}
                        requests.patch(f"{API_URL}/v1/fascicoli/{id_sel}/validate", json=p, headers=HEADERS)
                        st.balloons()
                        st.rerun()
        else:
            st.success("Ottimo! Tutti i documenti caricati sono stati verificati e archiviati.")

# --- TAB 2: RICERCA RAPIDA ---
with tab_ricerca:
    st.header("🔍 Cerca tra le sentenze")
    q = st.text_input("Parola chiave (es. 'notifica', 'IMU', 'Venezia')")
    if q:
        r_res = requests.get(f"{API_URL}/v1/ricerca", params={"query": q}, headers=HEADERS)
        if r_res.status_code == 200:
            for r in r_res.json():
                st.write(f"### {r['organo_corrente']} n. {r['numero_sentenza_corrente']}")
                st.write(r['massima_corrente'])
                st.divider()

# --- TAB 3: 📚 ARCHIVIO MASSIME (IL NUOVO REPERTORIO) ---
with tab_archivio:
    st.header("📚 Repertorio Ufficiale delle Massime")
    st.write("Qui trovi l'elenco completo di tutti i principi di diritto validati, pronti per la consultazione o l'esportazione.")

    # Recuperiamo l'archivio completo dal Backend
    arch_res = requests.get(f"{API_URL}/v1/archivio", headers=HEADERS)
    
    if arch_res.status_code == 200:
        archivio_dati = arch_res.json()
        if not archivio_dati:
            st.warning("L'archivio è ancora vuoto. Valida le sentenze nella prima scheda per vederle qui.")
        else:
            # Creiamo un DataFrame per una visualizzazione a tabella professionale
            df_arch = pd.DataFrame(archivio_dati)
            
            # 1. Bottone per scaricare l'archivio in Excel/CSV
            csv = df_arch.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Scarica Archivio Completo (CSV)",
                data=csv,
                file_name="archivio_massime_acdt.csv",
                mime="text/csv",
            )

            st.markdown("---")

            # 2. Visualizzazione a schede espandibili (molto leggibile)
            for index, row in df_arch.iterrows():
                with st.container():
                    col_info, col_link = st.columns([0.8, 0.2])
                    with col_info:
                        st.subheader(f"⚖️ {row['organo']} - Sent. {row['numero']}")
                        st.markdown(f"**Massima:**")
                        st.write(row['massima'])
                    with col_link:
                        # Link al PDF rinominato correttamente
                        st.link_button("📄 Apri PDF", f"{API_URL}{row['file_url']}")
                    st.divider()
    else:
        st.error("Errore nel caricamento dell'archivio.")
