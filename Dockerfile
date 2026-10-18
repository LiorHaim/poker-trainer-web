FROM python:3.12-slim

# Run as a non-root user. The image previously ran everything as root, which
# OpenShift's restricted SCC does not want and which gives a compromised
# process far more than it needs.
RUN useradd --create-home --uid 1001 --gid 0 trainer

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# OpenShift's restricted SCC ignores USER and runs the container as an
# arbitrary UID in group 0, so ownership by a specific user is useless there -
# the group bits are what the process actually gets. Granting group 0 the same
# access as the owner works under both OpenShift and a plain `docker run`.
RUN chgrp -R 0 /app && chmod -R g=u /app
USER 1001

EXPOSE 8080

# The readiness signal the deployment should probe: reports chart count and
# database connectivity, and returns 503 when either is missing.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health').status==200 else 1)"

# Training state now travels in a signed token rather than a per-process dict,
# so more than one worker is safe. Every worker must share the same SECRET_KEY,
# or a hand dealt by one is rejected by another.
ENV GUNICORN_WORKERS=2
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:8080 --workers ${GUNICORN_WORKERS} --access-logfile - app:app"]
