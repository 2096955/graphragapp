# Security

## Supported deployment shape

The production profile assumes the service sits behind TLS termination and a
trusted ingress or API gateway. The application bearer token is a service
boundary, not a replacement for end-user identity or fine-grained
authorisation.

## Secrets

Never commit environment files, API keys, bearer tokens, Arize credentials, or
the compliance hashing key. Production must provide at least:

- API_TOKEN
- COMPLIANCE_HASH_KEY, generated randomly and at least 32 characters, when
  ENABLE_COMPLIANCE=true (that flag defaults off in production)

Use the deployment platform's secret manager. Rotate any credential that has
ever appeared in repository history or a terminal or chat transcript.

## Compliance identifiers

Production pattern and attempt identifiers are keyed HMAC-SHA256 values. The key
must remain server-side. These identifiers are pseudonymous, not anonymous.
Treat the graph as sensitive operational data and apply access control,
retention, and deletion policies.

## Reporting

Do not open a public issue containing credentials, private payloads, production
logs, or customer data. Reproduce with synthetic data and rotate exposed
secrets before sharing diagnostics.
