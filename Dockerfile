FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[dashboard,api,kaggle]"
COPY sql ./sql
COPY app ./app
RUN useradd -m appuser && mkdir -p /app/data && chown -R appuser /app/data
USER appuser
EXPOSE 8501 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:%s/%s' % (os.getenv('HEALTH_PORT','8501'), os.getenv('HEALTH_PATH','_stcore/health')))" || exit 1
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0"]
