FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p run_state run_reports \
    && chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/run_state", "/app/run_reports"]

CMD ["python", "run_spider.py"]
