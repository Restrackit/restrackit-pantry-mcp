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
Gateway endpoint, no per-store infrastructure to provision, and no tenant
registry of any kind. Each tenant authenticates with **their own** Keycloak
account (created by restrackit-core's onboarding flow) via the OAuth login
flow described below — pantry-mcp holds no shared credential that can
address every store, so a routing bug here can misdirect a request to the
wrong store, but it can never authenticate as a different tenant's account.

Isolation is enforced per request, from the user's own access token:
- pantry-mcp validates the token Claude sends (issued by Keycloak to
  `pantry-mcp-connector` for that specific user) and reads the `store_id`
  claim from it (`pantry_mcp/jwks.py`, `_extract_store_id` in
  `pantry_mcp/server.py`);
- it then exchanges that token server-side, via RFC 8693 Standard Token
  Exchange, for one scoped to `restrackit-backend` (`pantry_mcp/auth.py`,
  `TokenExchanger`) and forwards it with `X-Target-Store: <store_id>` on every
  restrackit-core call.

There is no DynamoDB table, no per-tenant Secrets Manager credential, and no
`add_tenant.py`-style provisioning script — the only shared secret is the
token-exchange client's own credential (see "Deployment" below).

## One-time setup (per tenant)

Tenants onboard via OAuth token exchange: a tenant logs in for the first
time through the "Sign in now" button in the custom connector registered in
Claude (Desktop/mobile). No manual provisioning steps required.

1. Ensure restrackit-core has a store created for this tenant (requires an
   `ADMIN_ALL` account). Once the store exists, the tenant is ready to
   authenticate via the connector.

2. Tenant registers the custom connector in Claude:
   - Copy the `ApiUrl` from the CDK deployment output (its `/mcp` path is the
     MCP endpoint).
   - In Claude (Desktop/mobile), add the connector as a Custom Connector,
     pointing at `<ApiUrl>/mcp`.
   - On first use, click "Sign in now". Claude discovers Keycloak
     automatically via `GET /.well-known/oauth-protected-resource`, so no
     manual client ID or redirect URI entry is needed on the tenant's side.
   - The token is exchanged server-side; no manual token provisioning is
     required.

## Deployment

Infrastructure is defined as AWS CDK (Python) under `infra/`:

```bash
cd infra
uv venv .venv && source .venv/bin/activate
uv pip install --python .venv -r requirements.txt
cdk deploy \
  --parameters KeycloakUrl=... \
  --parameters KeycloakRealm=... \
  --parameters KeycloakConnectorClientId=... \
  --parameters KeycloakExchangeClientId=... \
  --parameters RestrackitBackendClientId=... \
  --parameters RestrackitBaseUrl=... \
  --parameters McpPublicBaseUrl=...  # the ApiUrl output, no trailing slash
```

Take the `ApiUrl` output for tenants' connector URLs, and pass it back in as
`McpPublicBaseUrl` (it is only known after the first deploy — redeploy once
with it set).

Before the first deploy, create the token-exchange client secret manually,
once:

```bash
aws secretsmanager create-secret \
  --name pantry-mcp/token-exchange-client \
  --secret-string '<the secret configured on Keycloak's pantry-mcp-token-exchange client>'
```

This value must be **identical** to the secret configured for the
`pantry-mcp-token-exchange` client on the Keycloak side (provisioned from
restrackit-core's `scripts/provision_keycloak_realm.sh`). Nothing keeps the
two in sync automatically — rotating one without the other breaks every
token exchange with `invalid_client`.

## Development

```bash
uv sync --extra dev
uv run pytest
```
