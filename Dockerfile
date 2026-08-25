FROM python:3.14-alpine

RUN apk add --no-cache so:libgobject-2.0.so.0 so:libpango-1.0.so.0 so:libharfbuzz.so.0 so:libharfbuzz-subset.so.0 so:libfontconfig.so.1 so:libpangoft2-1.0.so.0
RUN apk add --no-cache font-liberation font-liberation-sans-narrow ttf-linux-libertine

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /code
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-cache --no-dev

COPY app ./app

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
