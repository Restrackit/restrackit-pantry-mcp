# restrackit-pantry-mcp

A remote [MCP](https://modelcontextprotocol.io) server that turns a snapshot
of a grocery receipt into an up-to-date household pantry. Talk to Claude,
snap a photo of your receipt or just say what you bought or used, and it
tracks quantities on your behalf — no barcode scanning, no manual data
entry, no rigid expiry-date bookkeeping.

Built on top of [restrackit-core](https://github.com/restrackit/restrackit-core),
restrackit's own inventory-traceability backend, reused here purely through
its public REST API — this project ships no changes to that codebase.

## How it works

Claude is multimodal, so it reads the receipt photo itself: no OCR pipeline
to build or maintain. For every line item it estimates a plausible expiry
date and storage location — `dispensa` (pantry), `frigo` (fridge), or
`congelatore` (freezer); other values are accepted but get a generic
fallback shelf life instead of a tuned one — from general knowledge, then
calls this server to persist it.
`restrackit-pantry-mcp` is a thin, fully stateless translation layer — it
holds no database of its own and defers every fact about inventory to
restrackit-core.

```text
Claude (Desktop/mobile)
   │  reads the receipt photo / listens to a spoken update
   │  estimates category + plausible expiry date per item
   ▼
restrackit-pantry-mcp (AWS Lambda + API Gateway, MCP Streamable HTTP)
   │  translates tool calls into authenticated REST requests
   ▼
restrackit-core REST API
```

## Tools exposed

| Tool | Purpose |
|---|---|
| `add_purchase` | Record a purchase — creates the product/category/storage method if missing, one batch per unit |
| `get_pantry_status` | Return how much of each product is currently on hand |
| `record_consumption` | Close out units of a product you've used up (oldest first) |

There's no dedicated "shopping list" tool — ask Claude what you're low on
and it reasons over `get_pantry_status` in the conversation.

## Multi-tenancy

A single deployment of this server can serve any number of independent
restrackit-core stores, each isolated from the others: one Lambda, one API
Gateway endpoint, no per-store infrastructure to provision. Each tenant
authenticates with **their own** Keycloak account (created by
restrackit-core's onboarding flow) — pantry-mcp holds no shared credential
that can address every store, so a routing bug here can misdirect a
request to the wrong store, but it can never authenticate as a different
tenant's account. Isolation is enforced by two per-tenant records, both
keyed by `store_id`:
- a DynamoDB entry (`PantryMcpTenants`) mapping the tenant's bearer token to
  their `store_id`;
- a Secrets Manager secret (`pantry-mcp/tenants/<store_id>`) holding that
  tenant's own Keycloak username/password.

See `pantry_mcp/tenants.py`, `pantry_mcp/credentials.py`, and
`docs/superpowers/specs/2026-09-23-multi-tenant-design.md` for the design
rationale.

## One-time setup (per tenant)

1. Create the tenant's store on restrackit-core (requires an `ADMIN_ALL`
   account):

   ```bash
   curl -X POST https://api.restrackit.example.com/v1/onboarding/stores \
     -H "Authorization: Bearer <admin token>" \
     -H "Content-Type: application/json" \
     -d '{"store_name": "<store name>", "manager": {"username": "<tenant-username>", "email": "<unique email>"}}'
   ```

   Use a unique email per tenant — Keycloak rejects duplicates. Note down
   the returned `store_id` and the response's `temporary_password`.

   This is the account pantry-mcp will use **for this tenant only**. Unlike
   a shared admin account, it has no access to any other store.

2. The returned password is temporary (`UPDATE_PASSWORD` required action) —
   password grant rejects it as-is. Log in once interactively (e.g. via
   restrackit-core's own login flow) as `<tenant-username>` to set a
   permanent password. This one-time step is per tenant, not per
   deployment.

3. Generate a bearer token and register the tenant — this writes both the
   DynamoDB entry and the Secrets Manager secret:

   ```bash
   TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
   python scripts/add_tenant.py "<tenant name>" <store_id> "$TOKEN" "<tenant-username>" "<permanent-password>"
   ```

4. Give the tenant the `ApiUrl` (from the CDK output) and their bearer
   token to register as a Custom Connector in Claude (Desktop/mobile).

## Deployment

Infrastructure is defined as AWS CDK (Python) under `infra/`:

```bash
cd infra
uv venv .venv && source .venv/bin/activate
uv pip install --python .venv -r requirements.txt
cdk deploy \
  --parameters KeycloakUrl=... \
  --parameters KeycloakRealm=... \
  --parameters KeycloakClientId=... \
  --parameters RestrackitBaseUrl=...
```

Take the `ApiUrl` output for tenants' connector URLs, and `TenantsTableName`
for use with `scripts/add_tenant.py`.

## Development

```bash
uv sync --extra dev
uv run pytest
```
