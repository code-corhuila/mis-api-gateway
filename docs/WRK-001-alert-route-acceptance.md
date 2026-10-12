# HU-WRK-001: Gateway Alert Read Boundary

Only /api/v1/alerts/expiry is published to Inventory. Worker evaluation and stock
event paths remain direct internal service calls, not browser routes. Gateway
forwards requests, does not store alerts or duplicate owner validation/classification.
Query strings and original credentials/correlation are retained. Arbitrary alert
subroutes are absent. Upstream errors remain authoritative, including role denial
and method rejection; a dependency outage uses the existing 503 envelope.

Baseline: develop b1b0c4e. Prepared in the official clone under tmp/repos-oficiales,
not the checkout used by the active dev system. No environment/token/DB change.
Validation uses the repository's Python 3.12/Docker Nginx suite, with stub upstreams.
Stub denial tokens test forwarding, not cryptographic identity/role enforcement.
2026-10-12: all 19 gateway tests passed in 47.251 seconds. Nginx was built in
project mis-gateway-check-44020, with synthetic upstreams and a random loopback
port. Containers and network were removed by teardown. Tests include the four
new alert-route cases plus the existing routing/CORS/timeout/rate-limit suite.
Live Inventory schema/API alignment, full signed HTTP acceptance, browser alert
view and QA are subsequent steps; this PR does not close HU-WRK-001.
