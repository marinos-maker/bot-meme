#!/bin/bash
# Avvia il bot/engine in background
python -m early_detector.main &

# Avvia la dashboard web in background
python -m early_detector.dashboard &

# Attendi che almeno uno dei due processi termini
# Se uno crasha, il container si riavvierà
wait -n
