"""Register a friend in the PantryMcpTenants DynamoDB table.

Usage:
    python scripts/add_tenant.py <name> <store_id> <token>

Generate the token yourself first, e.g.:
    python -c "import secrets; print(secrets.token_urlsafe(32))"

Requires AWS credentials with dynamodb:PutItem on the table (the same
account used to `cdk deploy`), and TENANTS_TABLE_NAME set in the
environment (see .env.example).
"""

import os
import sys

import boto3

from pantry_mcp.tenants import hash_token


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    name, store_id, token = sys.argv[1], sys.argv[2], sys.argv[3]
    table_name = os.environ["TENANTS_TABLE_NAME"]

    client = boto3.client("dynamodb")
    client.put_item(
        TableName=table_name,
        Item={
            "token_hash": {"S": hash_token(token)},
            "store_id": {"N": store_id},
            "name": {"S": name},
        },
    )
    print(f"Registered {name!r} (store_id={store_id}) in {table_name}.")
    print(f"Give them this bearer token (shown once, not stored anywhere): {token}")


if __name__ == "__main__":
    main()
