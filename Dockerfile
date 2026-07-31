FROM python:3.6.15-slim-buster

WORKDIR /app
COPY pipeguard ./pipeguard
COPY web ./web
COPY run.py ./

EXPOSE 8000
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
