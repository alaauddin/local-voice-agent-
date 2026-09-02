FROM python:3.13-slim AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid "${APP_GID}" kiosk \
    && useradd --uid "${APP_UID}" --gid kiosk --create-home --shell /usr/sbin/nologin kiosk

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=kiosk:kiosk . .
RUN mkdir -p /app/data /app/staticfiles \
    && chown -R kiosk:kiosk /app/data /app/staticfiles \
    && chmod +x /app/docker/entrypoint.sh

USER kiosk

EXPOSE 8008

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8008", "wazen_local.asgi:application"]
