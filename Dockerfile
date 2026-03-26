FROM python:3.12-slim

WORKDIR /app

# System deps for building native extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/
COPY knowledge/ knowledge/

# Create output directory
RUN mkdir -p output

# Install the project and all dependencies
RUN pip install --no-cache-dir -e .

CMD ["run_discord_bot"]
