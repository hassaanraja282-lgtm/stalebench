FROM python:3.12-slim
ARG BIFROST_VERSION=v2.4.0
ARG TARGETARCH=amd64
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /usr/local/bin/bifrost-http \
       "https://downloads.getmaxim.ai/bifrost/${BIFROST_VERSION}/linux/${TARGETARCH}/bifrost-http" \
    && chmod +x /usr/local/bin/bifrost-http
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV BIFROST_BIN=/usr/local/bin/bifrost-http BIFROST_APP_DIR=/app/.bifrost STALEBENCH_DATA=/app/data PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "uvicorn stalebench.server:app --host 0.0.0.0 --port ${PORT}"]
