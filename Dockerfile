FROM python:3.6.15-slim-buster

WORKDIR /app
COPY pipeguard ./pipeguard
COPY web ./web
COPY run.py ./
RUN mkdir -p /app/data

EXPOSE 8000
VOLUME ["/app/data"]
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
