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

## One-time setup

1. Create the "Home" store on restrackit-core (requires an `ADMIN_ALL`
   account):

   ```bash
   curl -X POST https://api.restrackit.example.com/v1/onboarding/stores \
     -H "Authorization: Bearer <admin token>" \
     -H "Content-Type: application/json" \
     -d '{"store_name": "Home", "manager": {"username": "restrackit-pantry-mcp", "email": "you@example.com"}}'
   ```

   Note down the returned `store_id` and `temporary_password`.

2. No manual Keycloak step is needed here — the onboarding call in step 1
   already assigned the `manager` realm role and set `temporary_password`.
   That password is *temporary* (Keycloak's `UPDATE_PASSWORD` required
   action), so it can't be used with `TokenProvider`'s password-grant flow
   as-is: log in interactively once to set a permanent password (or have an
   admin reset it via the Keycloak admin console / `kcadm.sh`), otherwise
   the server will fail to authenticate.

3. Copy `.env.example` to `.env` and fill in every value, including the
   `store_id` from step 1.

4. Run `python scripts/setup_catalog.py` to pre-populate a few starter
   categories and storage methods (optional — `add_purchase` creates
   anything missing on demand anyway).

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
  --parameters RestrackitBaseUrl=... \
  --parameters RestrackitStoreId=... \
  --parameters McpAuthToken=...
```

Take the `ApiUrl` from the output and register it as a Custom Connector in
Claude (Desktop/mobile), using the value of `MCP_AUTH_TOKEN` as its bearer
token.

## Development

```bash
uv sync --extra dev
uv run pytest
```
