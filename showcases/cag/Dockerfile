FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py corpus.py benchmark.py fake_model.py ./
COPY corpus/ corpus/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8092"]
