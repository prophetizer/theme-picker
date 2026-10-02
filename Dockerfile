# Theme Picker. Published as ghcr.io/prophetizer/theme-picker by
# .github/workflows/ci.yml on each v* tag; see DEPLOY.md for running it.
#
# The base is pinned by digest (python:3.12-slim, multi-arch index) and the one
# dependency by hash, so a rebuild of the same tag gets the same bits.
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    THEME_SWITCHER_DIR=/data \
    PICKER_CONFIG=/data/picker.yml

# pip is only needed for this one install. It is removed afterwards: nothing
# at runtime uses it, and the base image's copy carries CVEs that image
# scanners (rightly) report against anything that ships it.
# Debian security updates newer than the pinned base (PCRE2 at the time of
# writing). The distribution's own fixes, so not pinned.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && python -m pip uninstall -y pip \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12

WORKDIR /app
# /data exists and belongs to the runtime user before VOLUME declares it, so
# a named volume mounted there starts out writable (one created from a
# missing path is root's, and the picker could not save its state).
RUN mkdir -p /data && chown 1000:1000 /data
COPY server.py LICENSE ./
COPY picker/ ./picker/

# Not root. 1000:1000 matches the usual PUID/PGID; compose's `user:` overrides
# it to match whoever owns the data, Traefik and theme.park directories.
USER 1000:1000
EXPOSE 8090
VOLUME ["/data"]
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=4)"
CMD ["python3", "server.py"]
