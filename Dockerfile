FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
ARG APP_UID=1000
ARG APP_GID=1000
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid ${APP_GID} sinau \
    && useradd --uid ${APP_UID} --gid sinau --create-home sinau
COPY --chown=sinau:sinau . .
RUN mkdir -p /app/var/private /app/staticfiles && chown -R sinau:sinau /app/var /app/staticfiles
USER sinau
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "45", "--access-logfile", "-", "--access-logformat", "%(h)s %(m)s %(U)s %(s)s"]
