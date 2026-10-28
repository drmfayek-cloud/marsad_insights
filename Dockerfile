FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MARSAD_DATA=/data PORT=8000
RUN useradd --create-home --uid 10001 insights && mkdir -p /data && chown insights /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=insights . .
USER insights
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')" || exit 1
# One worker with threads: the SQLite file and dataset folder are shared safely, and uploads stay in one process.
CMD gunicorn --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT} app:app
