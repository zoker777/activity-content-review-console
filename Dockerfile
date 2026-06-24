FROM harbor.lifelift.com.cn:9443/base/python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY server.py ./
COPY static ./static
COPY data/manifest.json ./data/manifest.json

EXPOSE 8000

CMD ["python3", "server.py"]
