FROM python:3.11-slim

# Don't write .pyc files into the container, stream logs unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first (before copying code) so Docker cache reuses this
# layer on every code-only change — only re-runs pip on pyproject.toml changes
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Now copy the rest of the project
COPY . .

EXPOSE 8000

COPY scripts/start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]