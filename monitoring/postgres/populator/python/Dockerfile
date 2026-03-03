FROM python:3.12-slim

WORKDIR /app

COPY monitoring/postgres/populator/python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitoring/postgres/populator/python/populate.py .

ENTRYPOINT ["python", "populate.py"]
