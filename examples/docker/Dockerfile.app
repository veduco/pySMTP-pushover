FROM alpine:3.24.1

RUN apk update && \
    apk add --no-cache \
        python3 \
        py3-cryptography \
        py3-aiosmtpd \
        py3-passlib \
        py3-aiohttp \
        py3-httpx \
        py3-aiosmtplib

WORKDIR /app

COPY run_backend.py .
COPY core/ ./core/
COPY backend/ ./backend/

RUN chmod +x run_backend.py

ENV GATEWAY_CONFIG="/data/config.json"

EXPOSE 25

CMD ["python3", "run_backend.py"]
