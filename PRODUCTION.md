# Production deployment

This repository supports a hardened single-writer production profile while
keeping the lab and benchmark surfaces separate from the serving path.

## Required environment

Set the following values in the deployment secret and configuration system:

    APP_ENV=production
    API_TOKEN=<secret bearer token>
    ENABLE_COMPLIANCE=false
    COMPLIANCE_DB_PATH=/data/compliance.kuzu
    BACKENDS=catalogue,jev
    TYPESAFE_API_KEY=<if Jev is enabled>
    EVAL_ENABLED=false
    ENABLE_DEMO_ENDPOINTS=false
    ALLOW_HOSTED_COMPLIANCE=false
    ENABLE_DOCS=false

The application refuses to start in production without API_TOKEN.
ENABLE_COMPLIANCE defaults off in production. When ENABLE_COMPLIANCE=true,
also set COMPLIANCE_HASH_KEY to a random secret of at least 32 characters;
startup fails if that key is missing or shorter than 32 characters.

## Runtime shape

Run Uvicorn with one application worker for the embedded Kuzu compliance
database and mount /data on durable storage. Do not point several replicas at the same local Kuzu
path. To scale horizontally, move compliance state to a networked store or a
single serialized writer service first.

Put TLS, user or service identity, distributed rate limiting, and request-size
limits at the ingress or API gateway. The application's bearer token and
in-memory limiter are defence-in-depth for a single process, not a distributed
identity layer.

## Disabled in production by default

- benchmark execution at /api/eval
- destructive compliance demo reset at /api/compliance/example
- interactive API docs

Internal result, eval, and graph endpoints require the bearer token when
production mode is enabled. Hosted compliance decisions are also default-deny:
turn on ALLOW_HOSTED_COMPLIANCE only after an explicit processor, residency, and
data-handling review because that backend receives the compliance payload.

## Release gate

A production release should require:

1. CI tests and Python compilation pass.
2. The production Docker image builds with LOCAL_MODELS=false.
3. Secrets are supplied only by the deployment secret manager.
4. A writable persistent volume is mounted at /data when compliance memory is enabled.
5. Backup and restore for compliance state is tested.
6. Synthetic smoke tests pass through the real ingress.
7. Observability export is verified without raw payloads.
8. Historical development credentials have been rotated.

## Known scale-out work

The benchmark job registry and write-rate limiter are process-local. That is fine
for the single-writer deployment above. Before multi-replica serving, replace
them with a shared queue and rate-limit layer and move mutable graph state out of
the process-local embedded database.
