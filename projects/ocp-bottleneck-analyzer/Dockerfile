FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /opt/app-root/src
COPY --chown=1001:0 pyproject.toml README.md ./
COPY --chown=1001:0 src ./src
COPY --chown=1001:0 app ./app
RUN pip install --no-cache-dir ".[ui]"

ENV STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501
USER 1001
CMD ["streamlit", "run", "app/streamlit_app.py"]
