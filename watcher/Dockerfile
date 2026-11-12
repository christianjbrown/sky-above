FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# The speech clip, face and state volumes are created from these folders, so they start out writable by nobody.
RUN mkdir -p /var/lib/flights/speech /var/lib/flights/faces /var/lib/flights/state \
    && chown nobody:nogroup /var/lib/flights/speech /var/lib/flights/faces /var/lib/flights/state
USER nobody
CMD ["/app/.venv/bin/python", "-m", "flights_watcher"]
