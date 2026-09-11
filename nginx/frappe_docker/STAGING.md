# Deploying the X-Accel-Redirect handoff to staging / production

## What this changes

`/file/<File name>/<file_name>` currently streams from S3 **through** a gunicorn worker
in ~10MB ranged GETs. On a 15GB master image that pinned a worker for the whole
transfer and hit gunicorn's per-request `--timeout`, which in gthread kills the entire
worker (`gunicorn/workers/gthread.py:113` stamps the deadline, `:243-250` acts on it) —
seen as `WORKER TIMEOUT` in the backend log and `upstream prematurely closed connection`
in nginx, at a different byte count every attempt.

With this change Frappe answers with an empty 200 carrying
`X-Accel-Redirect: /dfp-s3-internal/<bucket>/<key>?<SigV4 query>` and **nginx** streams
the object from S3. Gunicorn is out of the data path, so `--timeout` no longer applies,
Range/resume works, and the S3 provider is never exposed to clients.

It is **opt-in and fails safe**: the handoff happens only when the site config key
`dfp_x_accel_redirect_prefix` is set *and* the request carries `X-Use-X-Accel-Redirect`
(which frappe_docker's stock nginx template already injects, and which Frappe itself
uses for private files). Miss either one and it falls back to the presigned 302.

## Already done and verified in dev

Code (in this repo, `dfp_external_storage/.../dfp_external_storage.py`):
- `dfp_x_accel_redirect_prefix()` — the gate described above
- `dfp_x_accel_redirect_location()` — presigned URL -> `/<prefix>/<bucket>/<key>?<query>`
- the branch in `file()` that emits the header instead of the 302

Verified against the dev site: byte-identical download (md5 match) on a key containing
spaces and parentheses; `206` + correct `Content-Range` on a ranged read of a 10.5GB
file; a real 3.18GB browser download served entirely by nginx (confirmed by nginx
holding one connection to the MinIO host and *zero* to gunicorn during the transfer);
files on presigned-off connections still proxied unchanged.

## Discover first — do not assume

1. **How app code reaches this host.** Apps are baked into the image (`apps.json` /
   `APPS_JSON_BASE64` / bake target), so this repo's commit must be pushed and the
   image rebuilt. Find the actual pipeline before planning the deploy. For a quick
   pre-deploy test only, the app directory can be bind-mounted over
   `/home/frappe/frappe-bench/apps/dfp_external_storage` in the `backend` service.
2. **The stock nginx template in the *running image*.** `frappe.conf.template` here was
   derived from one specific frappe_docker revision. Diff it against the image's own
   copy and rebase if they differ — upstream changes that template (e.g. the socket.io
   proto/origin fix):
   `docker compose exec frontend cat /templates/nginx/frappe.conf.template`
3. **The DFP External Storage connections on this site** — names, `endpoint`, `secure`,
   `presigned_urls`, `presigned_mimetypes_starting`, `remote_size_enabled`.
4. **That the frontend container can reach the S3 endpoint** by the exact host:port
   string in the DFP `endpoint` field: `docker compose exec frontend getent hosts <host>`
5. The current gunicorn flags, for context and rollback:
   `docker compose exec backend ps -o args= -C gunicorn`

## Steps

1. Rebuild/redeploy the image so the app code change is present in `backend`.
2. Copy `nginx/frappe_docker/frappe.conf.template` to the deploy directory. **Edit both
   `joshua.galcom.local:9000` occurrences** (the `upstream` and the `proxy_set_header
   Host`) to match this site's DFP endpoint exactly. They are hardcoded deliberately:
   `nginx-entrypoint.sh` runs `envsubst` with an explicit variable list, so a new
   variable of our own would not be substituted and nginx would fail on the literal text.
3. Bind-mount it into the frontend service, keeping the existing `sites` mount:
   ```yaml
   services:
     frontend:
       volumes:
         - sites:/home/frappe/frappe-bench/sites
         - ./frappe.conf.template:/templates/nginx/frappe.conf.template:ro
   ```
4. On the target connection (the one holding the large files), check **Presigned URLs**
   and set **Presigned Mimetypes Starting** to a prefix that matches them — master
   images are `.zip`, which guesses as `application/zip`, so `application/` works and
   the stock `video/` does not. An empty field presigns everything on that connection.
5. `docker compose exec backend bench set-config -g dfp_x_accel_redirect_prefix /dfp-s3-internal/`
6. `docker compose up -d frontend && docker compose restart backend`

## Verify, in this order

```bash
# 0. the template rendered and nginx is happy
docker compose logs frontend | tail -20
docker compose exec frontend nginx -t

# 1. a SMALL file on the presigned connection, through the site
curl -s -D - -o /tmp/a.bin 'https://<site>/file/<id>/<name>' | grep -iE '^HTTP/|Content-Length|ETag|Accept-Ranges'

# 2. the same object straight from S3, and compare
md5sum /tmp/a.bin   # must equal the object's md5 / the File doc content_hash

# 3. Range works (this is also the fastest proof the whole chain is live)
curl -s -D - -o /dev/null -r 0-1023 'https://<site>/file/<id>/<name>' | grep -iE '^HTTP/|Content-Range'
# expect: 206 Partial Content + Content-Range: bytes 0-1023/<full size>

# 4. regression: a file on a connection with presigned OFF still downloads
# 5. the real 15GB file end to end, then confirm the logs are clean:
docker compose logs frontend | grep -i 'prematurely closed'   # expect nothing
docker compose logs backend  | grep -i 'WORKER TIMEOUT'       # expect nothing
```

**Which path served a request?** If the response carries `ETag`, `Last-Modified` and
`Accept-Ranges: bytes`, it came from S3 via nginx — the Python proxy path sends none of
those. A `206` on a ranged request is conclusive. Do **not** test with `curl -I`: a
presigned URL signs the HTTP method, so a HEAD arriving with a GET signature returns
403. That is expected and harmless; browsers do not HEAD downloads.

## Failure modes

| Symptom | Cause |
|---|---|
| `403 SignatureDoesNotMatch` from S3 | nginx's `proxy_set_header Host` differs from the DFP `endpoint` string. SigV4 signs Host. |
| Empty 200, zero bytes | nginx has no location matching `dfp_x_accel_redirect_prefix`, or the front end is not nginx. |
| 404 from nginx | internal location missing or misspelled; check the rendered `/etc/nginx/conf.d/frappe.conf`. |
| Still slow / still times out | no handoff happening: presigned off, or the mimetype filter excludes the file. Check for the `ETag` tell above. |
| 302 to the S3 host instead | the gate declined — config key unset, or `X-Use-X-Accel-Redirect` not reaching the app. |

## Rollback

One key, no nginx revert, effective on the next request:

```bash
docker compose exec backend bench set-config -g dfp_x_accel_redirect_prefix ""
```

An empty value fails the gate, so `/file/` goes back to the presigned 302. To return all
the way to proxy-through-Frappe, also uncheck **Presigned URLs** on the connection.
