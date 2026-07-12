FROM alpine:3.24.1

RUN apk update && \
    apk add --no-cache \
        python3 \
        py3-requests \
        py3-cryptography \
        py3-aiosmtpd \
        py3-passlib

WORKDIR /app

COPY smtp_pushover.py .
RUN chmod +x smtp_pushover.py

ENV GATEWAY_CONFIG="/data/config.json" \
    VAULT_FILE="/data/vault.json" \
    VAULT_META_FILE="/data/vault_meta.json"

EXPOSE 25

CMD ["python3", "smtp_pushover.py"]
