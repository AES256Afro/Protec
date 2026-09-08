FROM python:3.14-slim
ARG PROTEC_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/AES256Afro/Protec" \
      org.opencontainers.image.title="Protec" \
      org.opencontainers.image.revision=$PROTEC_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROTEC_DATA=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd -g 10001 protec && useradd -u 10001 -g protec -M protec \
    && mkdir -m 0700 /data && chown 10001:10001 /data
COPY protec ./protec
COPY static ./static
USER 10001:10001
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=3).read()"
CMD ["gunicorn", "--no-control-socket", "--bind", "0.0.0.0:8765", "--workers", "1", "--threads", "4", "--timeout", "30", "--worker-tmp-dir", "/tmp", "protec.wsgi:create_app()"]
