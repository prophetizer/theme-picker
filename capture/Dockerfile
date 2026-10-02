# Theme Picker's screenshot capture, optional. Published as
# ghcr.io/prophetizer/theme-picker-capture by .github/workflows/ci.yml on each
# v* tag. Build from the repo root:
#
#   docker build -f capture/Dockerfile -t theme-picker-capture .
#
# It runs capture_theme_screenshots.py nightly (capture/run.py), which cycles
# the LIVE theme through every theme and photographs the apps in
# screenshots.apps for the picker's lightbox. Give it the same /data and
# proxy-config mounts and settings as the picker; see DEPLOY.md.
#
# The base is Microsoft's Playwright image for the pinned Playwright version
# (Ubuntu 24.04, Python 3.12, its own Chromium), pinned by digest; the Python
# packages are pinned by hash.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0

# Chromium's own sandbox is off here: Docker's default seccomp profile does
# not let it create its namespaces, so it would not start. The container is
# the boundary instead -- it holds no secrets, and needs only the picker's
# data and the proxy config directory.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    THEME_SWITCHER_DIR=/data \
    PICKER_CONFIG=/data/picker.yml \
    CAPTURE_BROWSER=chromium \
    CAPTURE_SANDBOX=false

# Ubuntu's OpenSSL security update, which the pinned base predates. Not
# pinned: it is the distribution's own fix, and the version moves only
# forward within 24.04.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade openssl libssl3t64 \
    && rm -rf /var/lib/apt/lists/*

# Then the capture's packages; afterwards pip and the virtualenv tooling the
# base ships go, as in the picker's image: nothing at runtime uses them, and
# they (and pip's vendored urllib3, msgpack, setuptools) carry CVEs that
# scanners rightly report.
COPY capture/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && python3 -m pip uninstall -y virtualenv distlib filelock platformdirs python-discovery pip \
    && rm -rf /root/.cache        # the base's virtualenv wheel cache, a second pip

WORKDIR /app
RUN mkdir -p /data && chown 1000:1000 /data
COPY LICENSE capture_theme_screenshots.py ./
COPY capture/run.py ./capture_run.py
COPY picker/ ./picker/

USER 1000:1000
VOLUME ["/data"]
CMD ["python3", "capture_run.py"]
