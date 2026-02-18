# 🚀 Solana Early Detector — Meme Coin Pre-Pump Detection Bot

Bot Python per il rilevamento anticipato di meme coin esplosive su Solana, basato su un **Instability Index** matematico che combina smart wallet intelligence, feature engineering e scoring cross-sectional.

## Architettura

```
early_detector/
├── config.py           # Configurazione + env vars
├── db.py               # Connessione async PostgreSQL (Supabase)
├── collector.py        # Fetch dati da Birdeye / DexScreener
├── features.py         # Feature engineering matematico
├── smart_wallets.py    # Wallet analysis + KMeans clustering
├── scoring.py          # Instability Index + z-scores
├── signals.py          # Trigger + filtri sicurezza + Telegram
├── optimizer.py        # ML weight optimization (LogisticRegression)
├── backtest.py         # Replay engine + equity curve
└── main.py             # Loop asincrono principale (60s)
```

## Quick Start

### 1. Setup

```bash
# Clona e entra nella directory
cd bot-meme

# Crea virtual environment
python -m venv venv
source venv/bin/activate   # Linux/Mac
# oppure: venv\Scripts\activate  # Windows

# Installa dipendenze
pip install -r requirements.txt
```

### 2. Configurazione

```bash
# Copia il template e inserisci le tue chiavi
cp .env.example .env
```

Modifica `.env` con:
- **SUPABASE_DB_URL** — URL PostgreSQL da Supabase
- **BIRDEYE_API_KEY** — Chiave API Birdeye
- **TELEGRAM_BOT_TOKEN** + **TELEGRAM_CHAT_ID** — Per ricevere alert

### 3. Database

Esegui la migration SQL su Supabase:

```bash
# Vai su Supabase Dashboard → SQL Editor → incolla il contenuto di:
# migrations/001_initial_schema.sql
```

### 4. Esecuzione

```bash
# Avvia il bot
python -m early_detector.main
```

### 5. Test

```bash
python -m pytest tests/ -v
```

## Formula Core — Instability Index

```
II = 2·Z(SA) + 1.5·Z(H) + 1.5·Z(VS) + 2·Z(SWR) − 2·Z(sell_pressure)
```

| Feature | Descrizione |
|---|---|
| **SA** | Stealth Accumulation — accumulazione silenziosa |
| **H** | Holder Acceleration — derivata seconda crescita holder |
| **VS** | Volatility Shift — compressione → breakout |
| **SWR** | Smart Wallet Rotation — rotazione capitale smart money |
| **sell_pressure** | Pressione di vendita (penalizzata) |

Segnale quando `II > percentile_95` con filtri di sicurezza (liquidity, mcap, concentrazione).

## Deploy (VPS Linux)

```bash
# Copia il service file
sudo cp deploy/earlydetector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable earlydetector
sudo systemctl start earlydetector

# Controlla i log
sudo journalctl -u earlydetector -f
```

## ⚠️ Disclaimer

Questo è un bot di **analisi e segnali**. L'uso in trading reale comporta rischi finanziari significativi. I risultati di backtest non garantiscono performance future.
