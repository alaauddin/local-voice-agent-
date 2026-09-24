# syntax=docker/dockerfile:1.6
FROM python:3.13-slim AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_TRIM_THRESHOLD_=100000 \
    TZ=Asia/Aden

WORKDIR /app

RUN groupadd --gid "${APP_GID}" kiosk \
    && useradd --uid "${APP_UID}" --gid kiosk --create-home --shell /usr/sbin/nologin kiosk

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    apt-get update -qq \
    && apt-get install -y --no-install-recommends build-essential tini \
    && python -m pip install --upgrade pip \
    && pip install --no-compile -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && find /usr/local/lib/python3.13 -type d -name __pycache__ -prune -exec rm -rf {} + \
    && find /usr/local -type f -name "*.pyc" -delete

COPY --chown=kiosk:kiosk . .
RUN mkdir -p /app/data /app/staticfiles \
    && chown -R kiosk:kiosk /app/data /app/staticfiles \
    && chmod +x /app/docker/entrypoint.sh \
    && python -m compileall -q kiosk_agent wazen_local 2>/dev/null; true

USER kiosk

EXPOSE 8008

ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/app/docker/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8008", "wazen_local.asgi:application"]
