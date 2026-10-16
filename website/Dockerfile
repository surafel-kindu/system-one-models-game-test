FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BENCHMARK_DIR=/benchmarks DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 arcade \
    && useradd --uid 10001 --gid arcade --no-create-home arcade \
    && mkdir /data && chown arcade:arcade /data
COPY --chown=arcade:arcade . .
USER arcade
EXPOSE 8000
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "45", "--access-logfile", "-", "--error-logfile", "-"]
