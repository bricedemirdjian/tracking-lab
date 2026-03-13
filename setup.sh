#!/bin/bash
echo "=============================================="
echo "  TikTok Tracker - Merci Lab - Installation"
echo "=============================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERREUR: Python3 n'est pas installe."
    echo "Installez Python3: https://www.python.org/downloads/"
    exit 1
fi

echo "[1/3] Creation de l'environnement virtuel..."
python3 -m venv venv
source venv/bin/activate

echo "[2/3] Installation des dependances..."
pip install -r requirements.txt --quiet

echo "[3/3] Initialisation de la base de donnees..."
python3 database.py

echo ""
echo "=============================================="
echo "  Installation terminee !"
echo ""
echo "  Pour lancer le dashboard :"
echo "    ./start.sh"
echo ""
echo "  Ou manuellement :"
echo "    source venv/bin/activate"
echo "    python3 app.py"
echo "=============================================="
