FROM python:3.12.3-slim
RUN pip install --no-cache-dir "psycopg[binary]==3.3.6" "redis==8.1.0"
COPY app.py /app/app.py
EXPOSE 8000
CMD ["python3", "/app/app.py"]
