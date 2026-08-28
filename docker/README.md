# Frappe v16 lifecycle test stack

This disposable, internal-only Compose project builds ERPNext `v16.33.0`, Frappe `v16.31.0` and the current compatibility fork, then runs the app's real S3 lifecycle suite against VersityGW. It publishes no host ports and uses only relative bind mounts.

Copy `.env.example` to `.env`, replace every generated-secret placeholder, then run:

```sh
docker compose -f compose.test.yaml config --quiet
docker compose -f compose.test.yaml build
docker compose -f compose.test.yaml up --abort-on-container-exit --exit-code-from tester tester
docker compose -f compose.test.yaml down
```

The suite covers upload/read, `get_content(encodings=[])`, rename, public-to-private transition, unauthorised private download, amendment-style copy, shared-object deletion, local-to-S3, S3-to-S3, S3-to-local, fail-closed writes, transaction rollback and final deletion.
