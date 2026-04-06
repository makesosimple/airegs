#!/bin/bash
# ITO Crawler — .env.ito konfigürasyonu ile ito_docs collection'ına yazar
# Kullanım: cd backend && source venv/Scripts/activate && bash run_ito_crawler.sh

export AIREGS_ENV_FILE=.env.ito
python ito_crawler.py
