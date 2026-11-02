FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 collector \
    && useradd --uid 10001 --gid collector --no-create-home collector \
    && mkdir /data && chown collector:collector /data
COPY collector ./collector
USER collector
EXPOSE 8080/tcp 18512/udp
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=8s --start-period=10s --retries=3 \
    CMD ["python", "-m", "collector.healthcheck"]
CMD ["python", "-m", "collector"]
