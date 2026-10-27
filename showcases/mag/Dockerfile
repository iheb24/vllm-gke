FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py pipeline.py memory_store.py fake_model.py ./

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8093"]
