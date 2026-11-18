# Credit card dispute demo: web console + Conductor workers in one container.
#
# Build (from this folder):
#   docker build -t dispute-demo .            # or: podman build -t dispute-demo .
#
# Run (open http://localhost:8000/ when it says "Dispute console"; Ctrl+C to stop):
#   docker run --rm -it -p 8000:8000 --env-file ../.env dispute-demo
#
# Environment variables (pass with --env-file or -e; never bake them into the image):
#   CONDUCTOR_FLAVOR       optional  "orkes" or "oss". Default: orkes if CONDUCTOR_AUTH_KEY is set, else oss.
#   CONDUCTOR_SERVER_URL   required  Conductor API URL ending in /api:
#                                    Orkes: https://<cluster>.orkesconductor.io/api
#                                    OSS on this machine: http://host.containers.internal:8080/api
#                                    (Docker Desktop: http://host.docker.internal:8080/api)
#   CONDUCTOR_AUTH_KEY     Orkes     access key id of an Orkes application (not used on OSS)
#   CONDUCTOR_AUTH_SECRET  Orkes     access key secret
#                          The application needs the Worker, Metadata API and Business Rule Manager roles.
#   CONDUCTOR_UI_URL       optional  UI address for the console's links, when it is not the server URL
#                                    minus /api (e.g. http://localhost:8080 when the API URL uses host.*.internal)
#   KEEP_DATA              optional  1 = skip the reset (keep earlier executions and demo data). Default 0.
#   MERCHANT_AUTO_REPLY_SECONDS  optional  seconds before auto-reply merchants answer. Default 20.
#   PORT                   optional  port inside the container. Default 8000 (change -p to match).
#
# On start the container checks the connection, saves the triage rules and registers the workflows in
# Conductor, resets the demo (terminates earlier dispute_* executions, reseeds the bank data), then runs
# the console and the workers. Demo data lives inside the container and starts fresh on every run.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 demo \
    && chown -R demo:demo /app \
    && chmod +x docker-entrypoint.sh
USER demo

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
