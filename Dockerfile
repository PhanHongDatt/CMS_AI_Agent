FROM python:3.12-slim

# FIX (2026-09-15): base image tích luỹ nhiều CVE OS-level (util-linux,
# ncurses, perl-base — Trivy chặn image scan trong Jenkins: 56 total, 3
# CRITICAL). apt-get upgrade để vá các gói đã có bản sửa upstream, dọn
# cache ngay trong cùng layer để không phình image.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
