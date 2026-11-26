FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml requirements-server.lock ./
COPY dntsne ./dntsne
RUN pip install --no-cache-dir -r requirements-server.lock && pip install --no-deps .
USER 1000:1000
EXPOSE 8787
CMD ["uvicorn", "dntsne.server:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]

