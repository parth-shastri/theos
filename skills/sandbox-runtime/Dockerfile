FROM opensandbox/code-interpreter:v1.1.0

ARG NODE_VERSION=24.21.0
ARG NODE_SHA256=6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2
ARG AGENT_BROWSER_VERSION=0.38.1
ARG DOCX_JS_VERSION=9.11.0
ARG PWC_COMMIT=dba15a776f9773282fa590f42d7496f2833b5959

ENV PATH="/opt/node/bin:/opt/theos/report-style/.venv/bin:${PATH}"
ENV NODE_PATH="/opt/node/lib/node_modules"
ENV CHROME="/usr/local/bin/google-chrome"
ENV AGENT_BROWSER_EXECUTABLE_PATH="/usr/local/bin/google-chrome"
ENV PLAYWRIGHT_BROWSERS_PATH="/opt/ms-playwright"
ENV MATPLOTLIBRC="/opt/theos/report-style/assets/matplotlibrc"

RUN set -eux; \
    test "$(dpkg --print-architecture)" = "arm64"; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils \
        fonts-dejavu-core fonts-liberation \
        libreoffice-writer libreoffice-calc pandoc poppler-utils qpdf tesseract-ocr; \
    node_file="node-v${NODE_VERSION}-linux-arm64.tar.xz"; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/${node_file}" -o /tmp/node.tar.xz; \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum --check -; \
    mkdir -p /opt/node; \
    tar -xJf /tmp/node.tar.xz --strip-components=1 -C /opt/node; \
    rm -f /tmp/node.tar.xz; \
    npm install --global --prefix /opt/node --allow-scripts=agent-browser \
        "agent-browser@${AGENT_BROWSER_VERSION}" "docx@${DOCX_JS_VERSION}"; \
    fc-cache -f; \
    fc-match "DejaVu Sans Mono"; \
    command -v soffice; \
    command -v pandoc; \
    command -v pdftoppm; \
    command -v pdfinfo; \
    command -v tesseract; \
    command -v qpdf; \
    agent-browser --version; \
    rm -rf /var/lib/apt/lists/* /root/.npm/_logs

COPY sandbox-runtime/requirements.lock /tmp/requirements.lock
COPY report-style /opt/theos/report-style/

RUN set -eux; \
    mkdir -p /usr/local/share/fonts/space-grotesk; \
    cp /opt/theos/report-style/assets/fonts/*.ttf /usr/local/share/fonts/space-grotesk/; \
    fc-cache -f; \
    test "$(fc-match -f '%{family}' 'Space Grotesk')" = 'Space Grotesk'

ENV PYTHONPATH="/opt/theos/report-style/.venv/lib/python3.14/site-packages"

RUN set -eux; \
    uv venv --python 3.14 /opt/theos/report-style/.venv; \
    uv pip install --python /opt/theos/report-style/.venv/bin/python -r /tmp/requirements.lock; \
    python -m playwright install --with-deps chromium; \
    chrome="$(find "${PLAYWRIGHT_BROWSERS_PATH}" -type f -name chrome -perm /111 -print -quit)"; \
    test -n "${chrome}"; \
    ln -s "${chrome}" /usr/local/bin/google-chrome; \
    uv pip install --python /opt/theos/report-style/.venv/bin/python \
        "git+https://github.com/huggingface/pwc-cli.git@${PWC_COMMIT}#subdirectory=standalone_cli"; \
    chmod +x /opt/theos/report-style/scripts/theos-report; \
    ln -s /opt/theos/report-style/scripts/theos-report /usr/local/bin/theos-report; \
    test -x /opt/code-interpreter/code-interpreter.sh; \
    test -x "${CHROME}"; \
    command -v theos-report; \
    python -c 'import arxiv, bs4, docx, markdown, markitdown, matplotlib, openpyxl, pandas, pdf2image, pdfplumber, pypdf, pypdfium2, playwright, pytesseract, reportlab'; \
    pwc version; \
    node -e 'require("docx")'; \
    rm -f /tmp/requirements.lock
