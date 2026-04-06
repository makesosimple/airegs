#!/bin/bash
# ITO Demo backend'i — port 8001, .env.ito konfigürasyonu ile çalışır
# Kullanım: cd backend && source venv/Scripts/activate && bash run_ito.sh

export AIREGS_ENV_FILE=.env.ito
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
