# Microsoft's Playwright image: Chromium plus every system library it needs, version-matched to the
# playwright package pinned in pyproject.toml.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# The image's Python is Ubuntu's system Python; inside a container that protection isn't needed.
RUN pip install --no-cache-dir --break-system-packages . \
    && mkdir -p /data && chown pwuser:pwuser /data

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
USER pwuser
CMD ["python", "-m", "uarb_agent"]
