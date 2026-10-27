FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py pipeline.py sql_guard.py db.py fake_model.py ./
COPY data/schema.sql data/seed.sql data/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091"]
