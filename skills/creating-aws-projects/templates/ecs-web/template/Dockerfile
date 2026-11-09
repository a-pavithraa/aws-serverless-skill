# Base image pinned by digest. Rebuild and redeploy when a new digest of python:3.13-slim ships
# security fixes; see docs/runbook.md.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ARG SOURCE_SHA256=unknown
ENV SOURCE_SHA256=${SOURCE_SHA256} PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080

WORKDIR /app
COPY app/ /app/
USER 65534:65534
EXPOSE 8080
CMD ["python", "server.py"]
