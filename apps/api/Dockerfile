# Hunter Community · API · Python 3.11 slim · 多阶段
#
# 为什么多阶段:单阶段版本把 build-essential(gcc/g++/头文件,约 400 MB)和
# libpq-dev 留在了运行层,而它们只在 pip 装包时可能用到 —— 镜像 1.32 GB 里
# 有三成是运行时一次也不会执行的编译器。
#
# 现在:builder 装进 venv,运行层只拷 venv。运行层保留 tesseract(OCR 要的是
# 二进制本身,不是编译器)与 curl(HEALTHCHECK)。
# P1 skeleton · minimal boot supported via HUNTER_MINIMAL_BOOT=1

# ─── builder ────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 有些包没有对应平台的 wheel 时要就地编译(arm64 上尤其常见),所以 builder 里
# 该给的编译工具还是得给 —— 只是不再让它们进运行层。
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 装进独立 venv 而不是 --target:uvicorn / alembic 这类 console_scripts 要留在
# bin/ 下才能直接当命令用,--target 装法会把它们丢在一个不在 PATH 上的目录里。
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install -r requirements.txt

# ─── runtime ────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

# curl · HEALTHCHECK
# tesseract-ocr · OCR 底层 · chi-sim=中文简体 · eng=英文(混排常见) · 用户上传截图批量加自选走这条链
# 注意:psycopg2-binary 自带 libpq,所以运行层不需要 libpq-dev / libpq5。
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# 排除项见 apps/api/.dockerignore(tests / __pycache__ / *.pyc 等不进镜像)
COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
