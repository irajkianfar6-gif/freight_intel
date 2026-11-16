FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m unittest discover tests
VOLUME ["/app/data", "/app/outputs"]
CMD ["sh", "scripts/run_loop.sh"]
