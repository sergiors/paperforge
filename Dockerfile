FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgobject-2.0-0 \
        libpango-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libfontconfig1 \
        libpangoft2-1.0-0 \
        fonts-liberation \
        fonts-liberation-sans-narrow \
        fonts-linuxlibertine \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=UTC \
    PATH="/code/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache

RUN mkdir -p /tmp/.cache/fontconfig \
    && chmod -R 1777 /tmp/.cache

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /code

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-cache --no-dev

COPY app ./app

EXPOSE 8000

CMD ["python", "-m", "app.entrypoint"]
