#!/bin/bash
echo "=============================================="
echo "  TikTok Tracker - Merci Lab"
echo "=============================================="

cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Environnement virtuel non trouve. Lancez d'abord ./setup.sh"
    exit 1
fi

echo ""
echo "  Dashboard disponible sur : http://localhost:5555"
echo "  Ctrl+C pour arreter"
echo ""
echo "=============================================="

python3 app.py
