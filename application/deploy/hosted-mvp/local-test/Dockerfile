# Local containerized hosting test image (Admin + Operator only).
# Not for production use; production builds use Dockerfile.admin and Dockerfile.operator.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EPM_APPLICATION_DIR=/opt/epm/app \
    EPM_DATA_DIR=/data \
    PYTHONPATH=/opt/epm/app/apps/server:/opt/epm/local-test

WORKDIR /opt/epm/app

COPY pyproject.toml /opt/epm/app/pyproject.toml
RUN python -m venv /opt/epm/venv \
    && python -c "import tomllib; p=tomllib.loads(open('pyproject.toml').read())['project']; print('\n'.join([*p['dependencies'], *p['optional-dependencies']['dev']]))" > /tmp/requirements.txt \
    && /opt/epm/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY alembic.ini /opt/epm/app/alembic.ini
COPY database /opt/epm/app/database
COPY demo /opt/epm/app/demo
COPY apps/server/app /opt/epm/app/apps/server/app
COPY apps/web/dist /opt/epm/app/apps/web/dist
COPY deploy/hosted-mvp/local-test /opt/epm/local-test

RUN mkdir -p /data && chown -R 65532:65532 /data

USER 65532:65532
EXPOSE 8000 8081
