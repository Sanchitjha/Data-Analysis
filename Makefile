.PHONY: install test lint etl large dashboard api alerts benchmark up
install:   ; pip install -e ".[dashboard,api,dev]"
lint:      ; ruff check src tests app
test:      ; pytest -q
etl:       ; invsales all
large:     ; invsales --preset large all
dashboard: ; streamlit run app/streamlit_app.py
api:       ; uvicorn invsales.api:app --port 8000
alerts:    ; invsales alerts
benchmark: ; python scripts/benchmark.py
up:        ; docker compose up --build
