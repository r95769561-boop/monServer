# MON Control Server — Dockerfile
# Configured for Hugging Face Spaces (UID 1000, Port 7860) & general cloud containers
FROM python:3.11-slim

# Create user 1000 (required for Hugging Face Spaces non-root sandbox)
RUN useradd -m -u 1000 user

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
RUN chown -R user:user /app

USER user

EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
