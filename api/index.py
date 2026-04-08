import os
import sys

# Set VERCEL env if not already set
os.environ.setdefault('VERCEL', '1')

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel expects the WSGI app to be named 'app'
