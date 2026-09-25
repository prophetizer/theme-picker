# Theme Picker. Published as ghcr.io/prophetizer/theme-picker by
# .github/workflows/ci.yml on each v* tag; see DEPLOY.md for running it.
#
# The base is pinned by digest (python:3.12-slim, multi-arch index) and the one
# dependency by hash, so a rebuild of the same tag gets the same bits.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    THEME_SWITCHER_DIR=/data \
    PICKER_CONFIG=/data/picker.yml

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /app
COPY server.py LICENSE ./
COPY picker/ ./picker/

# Not root. 1000:1000 matches the usual PUID/PGID; compose's `user:` overrides
# it to match whoever owns the data, Traefik and theme.park directories.
USER 1000:1000
EXPOSE 8090
VOLUME ["/data"]
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/current', timeout=4)"
CMD ["python3", "server.py"]
