# Pin the base image: the plain `slim` tag eventually moves to trixie, where
# libasound2 is renamed to libasound2t64 and this build hard-fails.
FROM python:3.11-slim-bookworm

# Install system dependencies for Playwright.
# nodejs is required by the execute_js RPC method; git is in the tool allowlist.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    nodejs \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Install Playwright browsers.
# This must land in a world-readable location: the install runs as root, but the
# container drops to the non-root `sandbox` user below. The default root-owned
# browser cache is unreadable there, which makes every browser_* RPC call fail.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && \
    chmod -R 777 /ms-playwright

# Create non-root user
RUN useradd -m -u 1000 sandbox && \
    mkdir -p /workspace && \
    chown -R sandbox:sandbox /workspace

USER sandbox
WORKDIR /workspace

# Copy RPC server
COPY rpc_server.py /home/sandbox/rpc_server.py

CMD ["python", "/home/sandbox/rpc_server.py"]