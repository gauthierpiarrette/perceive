FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
RUN pip install --no-cache-dir perceive && playwright install chromium
ENTRYPOINT ["perceive-mcp"]
