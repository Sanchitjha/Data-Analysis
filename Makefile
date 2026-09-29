.PHONY: install test lint etl dashboard alerts up
install:   ; pip install -e ".[dashboard,dev]"
lint:      ; ruff check src tests app
test:      ; pytest -q
etl:       ; invsales all
dashboard: ; streamlit run app/streamlit_app.py
alerts:    ; invsales alerts
up:        ; docker compose up --build
