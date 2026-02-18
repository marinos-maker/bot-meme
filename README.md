# 🚀 Solana Early Detector — Meme Coin Pre-Pump Detection Bot

Bot Python per il rilevamento anticipato di meme coin esplosive su Solana, basato su un **Instability Index** matematico che combina smart wallet intelligence, feature engineering e scoring cross-sectional.

Ora dotato di **Web Dashboard** interattiva e controlli di sicurezza on-chain avanzati tramite Helius RPC.

## Architettura

```
early_detector/
├── config.py           # Configurazione + env vars
├── db.py               # Connessione async PostgreSQL (Supabase)
├── collector.py        # Fetch dati Birdeye / DexScreener / Helius IO
├── helius_client.py    # Client RPC per sicurezza e analisi transazioni
├── features.py         # Feature engineering matematico
├── smart_wallets.py    # Wallet analysis + KMeans clustering
├── scoring.py          # Instability Index + z-scores
├── signals.py          # Trigger + filtri sicurezza + Telegram
├── analyst.py          # Integrazione AI (Gemini Flash 2.0)
├── dashboard.py        # Web Server FastAPI (Port 8050)
└── main.py             # Loop asincrono principale (60s)
```

## Nuove Funzionalità (v2.0)

### 🖥️ Web Dashboard
Un'interfaccia completa per monitorare il bot in tempo reale:
- **Panoramica**: KPI sui token tracciati, wallet profilati e segnali generati.
- **Segnali Live**: Lista dei token che hanno superato l'Instability Index, con analisi AI on-demand.
- **Copy Address**: Icona per copiare rapidamente l'indirizzo del token.
- **Auto-Refresh**: Aggiornamento automatico dei dati ogni 30 secondi.
- **Analisi AI**: Integrazione con **Google Gemini 2.0 Flash** per un verdetto "BUY/WAIT/AVOID" basato su dati on-chain.

### 🛡️ Sicurezza Avanzata (Helius RPC)
- **Mint Authority Check**: Rileva se l'autorità di mint è ancora abilitata (rischio inflazione infinita).
- **Freeze Authority Check**: Rileva se l'autorità di congelamento è attiva (rischio honeypot).
- **Stealth Accumulation Reale**: Conta i *veri* buyer unici analizzando le transazioni di swap grezze, invece di approssimazioni basate sul volume.

## Quick Start

### 1. Setup

```bash
# Clona e entra nella directory
cd bot-meme

# Crea virtual environment
python -m venv venv
# Attiva (Windows):
venv\Scripts\activate
# Attiva (Linux/Mac):
source venv/bin/activate

# Installa dipendenze
pip install -r requirements.txt
```

### 2. Configurazione

Copia il file `.env.example` in `.env` e configura:

```ini
SUPABASE_DB_URL=postgresql://...
BIRDEYE_API_KEY=...
HELIUS_API_KEY=...
GOOGLE_API_KEY=... (per AI Analyst)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### 3. Database

Assicurati di aver applicato le migrazioni SQL su Supabase (vedi `migrations/`).

### 4. Esecuzione

Il sistema è composto da due processi principali:

**1. Il Cervello (Detector Loop)**
Analizza il mercato, calcola l'Instability Index e genera segnali.
```bash
python -m early_detector.main
```

**2. L'Interfaccia (Web Dashboard)**
Visualizza i dati e permette l'interazione.
```bash
python -m early_detector.dashboard
```
Apri il browser su: `http://localhost:8050`

## Formula Core — Instability Index

```
II = 2·Z(SA) + 1.5·Z(H) + 1.5·Z(VS) + 2·Z(SWR) − 2·Z(sell_pressure)
```

| Feature | Descrizione | Miglioramento v2.0 |
|---|---|---|
| **SA** | Stealth Accumulation | Usa conteggio reale wallet unici tramite Helius |
| **H** | Holder Acceleration | Derivata seconda crescita holder |
| **VS** | Volatility Shift | Compressione pre-breakout |
| **SWR** | Smart Wallet Rotation | Analisi pattern wallet (Retail/Sniper/Insider) |
| **Security** | Filtri Sicurezza | Scarta token con Mint/Freeze Authority attivi |

Segnale quando `II > percentile_95` con filtri di sicurezza (liquidity > 40k, mcap < 3M, top10 < 35%).

## ⚠️ Disclaimer

Questo è un bot di **analisi e segnali**. L'uso in trading reale comporta rischi finanziari significativi. I risultati di backtest non garantiscono performance future. Indirizzi token e segnali sono a puro scopo informativo.
