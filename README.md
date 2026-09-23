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

## One-time setup (per friend)

1. Create their "Home" store on restrackit-core (requires an `ADMIN_ALL`
   account):

   ```bash
   curl -X POST https://api.restrackit.example.com/v1/onboarding/stores \
     -H "Authorization: Bearer <admin token>" \
     -H "Content-Type: application/json" \
     -d '{"store_name": "Casa di Marco", "manager": {"username": "restrackit-pantry-mcp", "email": "you@example.com"}}'
   ```

   Note down the returned `store_id`.

2. No manual Keycloak step is needed — one shared `ADMIN_ALL` service
   account (configured once at deploy time) can address any store via the
   `X-Target-Store` header. That account's `temporary_password` still needs
   a one-time interactive login to become permanent, as before, but that's
   only done once for the whole deployment, not per friend.

3. Generate a token and register them in the tenants table:

   ```bash
   TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
   python scripts/add_tenant.py "Marco" <store_id> "$TOKEN"
   ```

4. Give them the `ApiUrl` (from the CDK output) and their token to register
   as a Custom Connector in Claude (Desktop/mobile).

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
  --parameters KeycloakUsername=... \
  --parameters KeycloakPassword=... \
  --parameters RestrackitBaseUrl=...
```

Take the `ApiUrl` output for friends' connector URLs, and `TenantsTableName`
for use with `scripts/add_tenant.py`.

## Development

```bash
uv sync --extra dev
uv run pytest
```
