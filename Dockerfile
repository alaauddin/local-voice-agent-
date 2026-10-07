# syntax=docker/dockerfile:1.6
FROM python:3.13-slim AS base

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

FROM python:3.13 AS native-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_TRIM_THRESHOLD_=100000 \
    TZ=Asia/Aden

WORKDIR /app

COPY requirements.txt requirements-build.txt ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --no-compile --prefer-binary \
    -r requirements.txt \
    -r requirements-build.txt

COPY . .
RUN python setup.py build_ext --inplace --parallel "$(nproc)" \
    && python manage.py check \
    && mkdir -p /app/staticfiles \
    && python manage.py collectstatic --noinput --clear \
    && python manage.py test kiosk_agent.tests --noinput \
    && find kiosk_agent wazen_local -type f -name "*.so" -exec strip --strip-unneeded {} + \
    && find kiosk_agent wazen_local -type f -name "*.py" ! -name "__init__.py" ! -path "kiosk_agent/migrations/*" ! -path "kiosk_agent/tests/*" -delete \
    && find kiosk_agent wazen_local -type f -name "*.c" -delete \
    && rm -rf build *.egg-info kiosk_agent/tests test_ip_discovery.py setup.py requirements-build.txt \
    && python -m pip uninstall -y Cython setuptools \
    && find /usr/local/lib/python3.13 -type d -name __pycache__ -prune -exec rm -rf {} + \
    && find /usr/local -type f -name "*.pyc" -delete

FROM base AS runtime

RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends tini network-manager libglib2.0-bin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=native-builder /usr/local /usr/local
COPY --from=native-builder --chown=kiosk:kiosk /app /app

RUN mkdir -p /app/data /app/staticfiles \
    && chown -R kiosk:kiosk /app/data /app/staticfiles \
    && chmod +x /app/docker/entrypoint.sh

USER kiosk

EXPOSE 8008

ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/app/docker/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8008", "wazen_local.asgi:application"]
