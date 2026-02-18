# 🚀 Solana Early Detector v3.0 — Institutional Grade

Bot Python avanzato per il rilevamento di meme coin su Solana. Basato su un **Instability Index** asincrono e cross-sectional, potenziato da risk management istituzionale e intelligenza on-chain.

## 🌟 Novità v3.0 (Institutional Grade)

Il sistema è stato completamente riscritto con un'architettura **Pro-Level**:

### 🧠 Alpha Engine (Optimization)
- **Bayesian Probability**: Ogni segnale riceve una "Confidence Score" (Win P) aggiornata dinamicamente.
- **Kelly Criterion**: Calcolo della dimensione ottimale della posizione (Size) in base al rischio.
- **Monte Carlo Simulation**: Analisi di 10.000 scenari per calcolare il VaR (Value at Risk) e il Drawdown potenziale.

### 📈 Matematica Robusta (Phase 1 Cleanup)
- **Robust Z-Scores (Median/MAD)**: Standardizzazione dei dati immune agli outlier estremi del mercato meme.
- **Regime Detection**: Il bot rileva automaticamente stati **DEGEN** (volatili) o **STABLE** (accumulo) e adatta i pesi dello scoring in tempo reale.

### 🕵️ Intelligence Specialistica (Phase 2 Cleanup)
- **Coordinated Entry (Louvain-lite)**: Rilevamento di lanci "bundled" (wallet multipli che comprano nello stesso secondo).
- **Insider Probability (Psi)**: Score di rischio basato sulla coordinazione e sulla "freschezza" dei wallet.
- **Narrative Manager**: Classificazione automatica dei token (AI, Politics, Meme-Animals, ecc.) tramite analisi lessicale.

## Architettura del Progetto

```
early_detector/
├── optimization.py     # Alpha Engine (Bayesian, Kelly, Monte Carlo)
├── narrative.py        # Classificazione Narrative
├── scoring.py          # robust z-scores + Detect Regime
├── smart_wallets.py    # Cluster (K-Means) + Coordinated Entry
├── analyst.py          # AI Analyst (Google Gemini 2.0 Flash)
├── backtest.py         # Motore di simulazione storica
├── dashboard.py        # Web Server Pro Dashboard
└── main.py             # Orchestratore asincrono (v3.0 Async)
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
Configura `BIRDEYE_API_KEY`, `HELIUS_API_KEY`, `SUPABASE_DB_URL` e `GOOGLE_API_KEY`.

### 3. Migrazione Database
```bash
python migrate_sync.py
```

### 4. Avvio
```bash
# Avvia il bot (Cervello)
python -m early_detector.main

# Avvia la dashboard (Occhi)
python -m early_detector.dashboard
```

## Dashboard Pro
Accedi a `http://localhost:8050` per visualizzare:
- **Heatmap di Instabilità**: Per vedere dove si concentra il volume.
- **Narrative Flow**: Dominanza dei temi (es. AI vs Dog coins).
- **Pro Signals**: Segnali con Win Probability, Kelly Size e Insider Risk.

## 🛡️ Sicurezza e Risk Management
- **LP Lock Check**: Analisi dello stato dei pool Raydium/Pump.fun.
- **Creator Risk**: Analisi dello storico del creatore per identificare serial ruggers.
- **Auto-Wait**: Segnali filtrati se la Win Probability è < 60%.

---
**⚠️ Disclaimer**: Questo software è a scopo puramente educativo. Il trading di criptovalute ad alta volatilità comporta il rischio di perdita totale del capitale.
