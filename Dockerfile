FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 先装依赖层，利用 Docker 层缓存
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache .

COPY . .

RUN useradd -m -u 1000 basepilot && chown -R basepilot:basepilot /app
USER basepilot

ENTRYPOINT ["basepilot-mcp"]
CMD ["--help"]
