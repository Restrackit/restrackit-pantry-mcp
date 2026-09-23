"""Register a tenant: a DynamoDB entry (bearer token -> store_id) plus a
Secrets Manager secret holding their own Keycloak credentials.

Usage:
    python scripts/add_tenant.py <name> <store_id> <token> <keycloak_username> <keycloak_password>

Generate the token yourself first, e.g.:
    python -c "import secrets; print(secrets.token_urlsafe(32))"

The Keycloak account must already have a *permanent* password: the
`temporary_password` returned by `/onboarding/stores` requires one
interactive login to become permanent before Keycloak will accept it in a
password grant.

Requires AWS credentials with dynamodb:PutItem and
secretsmanager:CreateSecret/PutSecretValue (the same account used to
`cdk deploy`), and TENANTS_TABLE_NAME set in the environment (see
.env.example).
"""

import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

from pantry_mcp.credentials import secret_name
from pantry_mcp.tenants import hash_token


def _upsert_secret(client, name: str, secret_string: str) -> None:
    try:
        client.create_secret(Name=name, SecretString=secret_string)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceExistsException":
            raise
        client.put_secret_value(SecretId=name, SecretString=secret_string)


def main() -> None:
    if len(sys.argv) != 6:
        print(__doc__)
        sys.exit(1)

    name, store_id, token, keycloak_username, keycloak_password = sys.argv[1:6]
    table_name = os.environ["TENANTS_TABLE_NAME"]

    dynamodb = boto3.client("dynamodb")
    dynamodb.put_item(
        TableName=table_name,
        Item={
            "token_hash": {"S": hash_token(token)},
            "store_id": {"N": store_id},
            "name": {"S": name},
        },
    )

    secret = secret_name(int(store_id))
    secretsmanager = boto3.client("secretsmanager")
    _upsert_secret(
        secretsmanager,
        secret,
        json.dumps({"username": keycloak_username, "password": keycloak_password}),
    )

    print(f"Registered {name!r} (store_id={store_id}) in {table_name}.")
    print(f"Stored Keycloak credentials in Secrets Manager as {secret!r}.")
    print(f"Give the tenant this bearer token (shown once, not stored anywhere): {token}")


if __name__ == "__main__":
    main()
