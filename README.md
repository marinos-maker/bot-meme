# 🚀 Solana Early Detector v5.0 — Automated Trading Module

Bot Python avanzato per il rilevamento e **trading automatico** di meme coin su Solana. Basato su un **Instability Index** asincrono, potenziato da risk management istituzionale, intelligenza on-chain e **esecuzione ordini ultra-veloce**.

## 🌟 Novità v5.0 (Automated Trading)

Il sistema ora include un modulo di trading completo integrato direttamente nel dashboard:

### 🤖 Trading Engine & Execution
- **Jupiter V6 Swap**: Integrazione diretta con Jupiter Aggregator per trovare sempre il miglior prezzo (Best Route).
- **Auto-Trade**: Esecuzione automatica dei segnali AI (BUY) con importi configurabili.
- **TP/SL Monitor**: Worker asincrono che monitora le posizioni ogni 10 secondi e vende automaticamente su Target Profit o Stop Loss.
- **Direct Dashboard Trading**: Pulsanti BUY/SELL rapidi direttamente dall'interfaccia web.

### 🧠 Alpha Engine (Optimization)
- **Bayesian Probability**: Ogni segnale riceve una "Confidence Score" (Win P) aggiornata dinamicamente.
- **Kelly Criterion**: Calcolo della dimensione ottimale della posizione (Size) in base al rischio.
- **Monte Carlo Simulation**: Analisi di 10.000 scenari per calcolare il VaR (Value at Risk).

### 📈 Matematica Robusta
- **Regime Detection**: Il bot rileva stati **DEGEN** (volatili) o **STABLE** e adatta i pesi dello scoring.
- **Insider Probability**: Score di rischio basato sulla coordinazione dei wallet nei primi minuti del lancio.

## Architettura del Progetto

```
early_detector/
├── trader.py           # Trading Engine (Jupiter V6 + Helius RPC)
├── tp_sl_monitor.py    # TP/SL Background Worker
├── optimization.py     # Alpha Engine (Bayesian, Kelly, Monte Carlo)
├── narrative.py        # Classificazione Narrative
├── scoring.py          # Robust Z-Scores + Regime Detection
├── smart_wallets.py    # Cluster Analysis + Copy Trading Logic
├── analyst.py          # AI Analyst (Google Gemini 2.0 Flash)
├── dashboard.py        # Web Server Pro Dashboard + Trading API
└── main.py             # Orchestratore asincrono (v4.0 Async)
```

## Quick Start

### 1. Installazione
```bash
git clone ...
cd bot-meme
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configurazione (.env)
Aggiungi le chiavi necessarie nel file `.env`:
```bash
# Data Providers
BIRDEYE_API_KEY=la_tua_chiave
HELIUS_API_KEY=la_tua_chiave
SUPABASE_DB_URL=postgresql://...
GOOGLE_API_KEY=la_tua_chiave

# Trading (NUOVO v5.0)
WALLET_PRIVATE_KEY=la_tua_chiave_phantom_base58
TRADE_AMOUNT_SOL=0.1
DEFAULT_TP_PCT=50
DEFAULT_SL_PCT=30
AUTO_TRADE_ENABLED=true
```

### 3. Migrazione Database
```bash
# Esegui lo script SQL migrations/002_trades.sql nel tuo DB Supabase
```

### 4. Avvio
```bash
# Avvia il bot (Cervello + Trading Auto)
python -m early_detector.main

# Avvia la dashboard (Interfaccia Trading)
python -m early_detector.dashboard
```

## Dashboard Pro (v5.0)
Accedi a `http://localhost:8050`:
- **💰 Posizioni**: Tabella in tempo reale di tutti i trade aperti con ROI live.
- **⚡ Segnali**: Clicca su 🟢 BUY per aprire posizioni manualmente.
- **🪙 Wallet**: Monitoraggio saldo SOL e storico performance.
- **Heatmap**: Visualizzazione grafica della liquidità e instabilità.

## 🛡️ Sicurezza
- **Circuit Breakers**: Protezione API anti-ban (429) per Helius e Birdeye.
- **Key Management**: Le chiavi private sono caricate solo da variabili d'ambiente e mai loggate.
- **Slippage Protection**: Impostazioni di default (2%) per evitare front-running eccessivo.

---
**⚠️ Disclaimer**: Questo software gestisce fondi reali e criptovalute ad alta volatilità. Usare con cautela e a proprio rischio. L'autore non è responsabile per eventuali perdite finanziarie.
