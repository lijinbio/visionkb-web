# ghcr.io/lijinbio/visionkb-web:<version>
# Build from the repository root:  docker build -t visionkb-web:dev .
# Run (secrets as files; the API URL and token are server-side only):
#   docker run --rm -p 8780:8780 --read-only --tmpfs /tmp -v /path/to/secrets:/run/secrets:ro \
#     -e VISIONKB_API_URL=http://visionkb-api:8770/v1 -e VISIONKB_API_TOKEN_FILE=/run/secrets/api_token_read \
#     -e VISIONKB_WEB_SECRET_FILE=/run/secrets/web_secret -e VISIONKB_WEB_ACCESS_CODES_FILE=/run/secrets/web_access_codes \
#     visionkb-web:dev
FROM python:3.13.18-slim-trixie AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# git: the two MCP packages are installed from the aiscientist-mcp commit pinned in uv.lock (tag visionkb-kg-v0.0.1)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
    && pip install uv==0.13.7
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY scripts/fetch_skill.py ./scripts/
# PyPI dependencies pinned with hashes from uv.lock; git dependencies pinned by commit from uv.lock; then the package.
RUN uv export --locked --no-dev --no-emit-project --no-emit-package aiscientist-mcp-common \
        --no-emit-package aiscientist-mcp-visionkb-kg --format requirements-txt -o /tmp/requirements.txt \
    && uv export --locked --no-dev --no-emit-project --no-hashes --format requirements-txt \
        | grep -E '^aiscientist-mcp-(common|visionkb-kg) @ git\+https://github.com/lijinbio/aiscientist-mcp@[0-9a-f]{40}#' > /tmp/git.txt \
    && test "$(wc -l < /tmp/git.txt)" = 2 \
    && pip install --prefix=/install --require-hashes -r /tmp/requirements.txt \
    && pip install --prefix=/install --no-deps -r /tmp/git.txt \
    && pip install --prefix=/install --no-deps .
# The skill: aiscientist-skills release zip, verified against the release SHA256SUMS and the digest pinned here.
ARG SKILLS_VERSION=0.2.1
ARG SKILLS_ZIP_SHA256=0a47d095def794c1e80d8b3d3a1d9ec269d901de029ae9d6b99ad5e45fa9c7d2
RUN python scripts/fetch_skill.py --version "${SKILLS_VERSION}" --zip-sha256 "${SKILLS_ZIP_SHA256}" --out /skill

FROM python:3.13.18-slim-trixie
ARG VERSION=dev
ARG SKILLS_VERSION=0.2.1
LABEL org.opencontainers.image.source="https://github.com/lijinbio/visionkb-web" \
      org.opencontainers.image.description="VisionKB home page and chat (bring your own Claude API key)" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      io.github.lijinbio.visionkb-web.skills-release="v${SKILLS_VERSION}"
COPY --from=build /install /usr/local
COPY --from=build /skill /opt/visionkb-web/skill
RUN groupadd --system --gid 10001 visionkb \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin visionkb \
    && test -x /usr/local/bin/visionkb-kg-mcp && test -s /opt/visionkb-web/skill/SKILL.md \
    && python -c "import anthropic, mcp, visionkb_web, aiscientist_mcp.visionkb_kg.server; print('visionkb-web', visionkb_web.__version__)"
# Runs with a read-only root filesystem: no bytecode writes; /tmp is the only scratch (tmpfs/emptyDir).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    VISIONKB_WEB_HOST=0.0.0.0 \
    VISIONKB_WEB_PORT=8780 \
    VISIONKB_WEB_SKILL_DIR=/opt/visionkb-web/skill
USER 10001:10001
EXPOSE 8780
# Healthy = ready: visionkb-api /v1/ready 200 and the MCP child up with its 8 tools (/readyz answers 503 otherwise).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('VISIONKB_WEB_PORT', '8780') + '/readyz', timeout=4)"]
CMD ["visionkb-web", "serve"]
