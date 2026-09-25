"""Test per la validazione JWT di pantry-mcp-connector via JWKS Keycloak."""

import time

import httpx
import pytest
import respx
from jose.utils import base64url_encode

import pantry_mcp.jwks as jwks_module
from pantry_mcp.config import Settings
from pantry_mcp.jwks import JWTValidationError, validate_user_token


@pytest.fixture(autouse=True)
def _reset_jwks_cache():
    """Isola i test resettando la cache JWKS in-process (module-level singleton)
    tra un test e l'altro, altrimenti un test successivo eredita il JWKS
    fetchato da un test precedente e non esercita davvero il cache-miss."""
    jwks_module._cache = jwks_module._JWKSCache()


def _settings() -> Settings:
    return Settings(
        keycloak_url="https://kc.example.com",
        keycloak_realm="restrackit",
        keycloak_connector_client_id="pantry-mcp-connector",
        keycloak_exchange_client_id="pantry-mcp-token-exchange",
        keycloak_exchange_client_secret="s3cr3t",
        restrackit_backend_client_id="restrackit-backend",
        restrackit_base_url="https://api.example.com/v1",
        mcp_public_base_url="https://pantry-mcp.example.com",
    )


def _make_rsa_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _jwk_from_public_key(public_key, kid: str) -> dict:
    numbers = public_key.public_numbers()

    def _b64(n: int) -> str:
        length = (n.bit_length() + 7) // 8
        return base64url_encode(n.to_bytes(length, "big")).decode()

    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


def _sign_token(private_key, kid: str, claims: dict) -> str:
    from jose import jwt as jose_jwt

    return jose_jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


@respx.mock
async def test_validate_user_token_accepts_valid_signed_token():
    """Un token firmato correttamente e con audience valida viene accettato."""
    private_key, public_key = _make_rsa_keypair()
    kid = "test-key-1"
    respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(return_value=httpx.Response(200, json={"keys": [_jwk_from_public_key(public_key, kid)]}))

    claims = {
        "iss": "https://kc.example.com/realms/restrackit",
        "aud": "pantry-mcp-connector",
        "sub": "user-1",
        "store_id": ["1"],
        "exp": int(time.time()) + 300,
    }
    token = _sign_token(private_key, kid, claims)

    payload = await validate_user_token(_settings(), token)

    assert payload["sub"] == "user-1"
    assert payload["store_id"] == ["1"]


@respx.mock
async def test_validate_user_token_rejects_expired_token():
    """Un token scaduto viene rifiutato con JWTValidationError."""
    private_key, public_key = _make_rsa_keypair()
    kid = "test-key-1"
    respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(return_value=httpx.Response(200, json={"keys": [_jwk_from_public_key(public_key, kid)]}))

    claims = {
        "iss": "https://kc.example.com/realms/restrackit",
        "aud": "pantry-mcp-connector",
        "sub": "user-1",
        "store_id": ["1"],
        "exp": int(time.time()) - 10,
    }
    token = _sign_token(private_key, kid, claims)

    try:
        await validate_user_token(_settings(), token)
        raise AssertionError("expected JWTValidationError")
    except JWTValidationError:
        pass


@respx.mock
async def test_validate_user_token_rejects_wrong_audience():
    """Un token con audience diversa dal client connector viene rifiutato."""
    private_key, public_key = _make_rsa_keypair()
    kid = "test-key-1"
    respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(return_value=httpx.Response(200, json={"keys": [_jwk_from_public_key(public_key, kid)]}))

    claims = {
        "iss": "https://kc.example.com/realms/restrackit",
        "aud": "some-other-client",
        "sub": "user-1",
        "store_id": ["1"],
        "exp": int(time.time()) + 300,
    }
    token = _sign_token(private_key, kid, claims)

    try:
        await validate_user_token(_settings(), token)
        raise AssertionError("expected JWTValidationError")
    except JWTValidationError:
        pass


@respx.mock
async def test_validate_user_token_rejects_unsigned_garbage():
    """Una stringa che non è nemmeno un JWT valido viene rifiutata."""
    respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(return_value=httpx.Response(200, json={"keys": []}))

    try:
        await validate_user_token(_settings(), "not-a-jwt")
        raise AssertionError("expected JWTValidationError")
    except JWTValidationError:
        pass


@respx.mock
async def test_validate_user_token_refetches_jwks_on_unknown_kid():
    """Simula una rotazione chiavi: la prima verifica fallisce con il JWKS in
    cache (vecchia chiave, che non può verificare la firma), il refetch
    forzato porta la chiave nuova e la seconda verifica passa — nessun
    secondo errore deve propagare.

    Nota: le due chiavi devono essere keypair RSA *diversi* (non solo `kid`
    diversi). python-jose itera su tutte le chiavi del JWKS a prescindere dal
    `kid` finché una verifica la firma, quindi con lo stesso keypair il primo
    tentativo riuscirebbe comunque e il retry non verrebbe mai esercitato.
    """
    _, old_public_key = _make_rsa_keypair()
    new_private_key, new_public_key = _make_rsa_keypair()
    old_kid, new_kid = "old-key", "new-key"

    route = respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(
        side_effect=[
            httpx.Response(200, json={"keys": [_jwk_from_public_key(old_public_key, old_kid)]}),
            httpx.Response(200, json={"keys": [_jwk_from_public_key(new_public_key, new_kid)]}),
        ]
    )
    claims = {
        "iss": "https://kc.example.com/realms/restrackit",
        "aud": "pantry-mcp-connector",
        "sub": "user-1",
        "store_id": ["1"],
        "exp": int(time.time()) + 300,
    }
    token = _sign_token(new_private_key, new_kid, claims)

    payload = await validate_user_token(_settings(), token)

    assert payload["sub"] == "user-1"
    assert route.call_count == 2


@respx.mock
async def test_validate_user_token_rejects_wrong_issuer():
    """A token signed by a different realm/issuer is rejected (I1)."""
    private_key, public_key = _make_rsa_keypair()
    kid = "test-key-1"
    respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(return_value=httpx.Response(200, json={"keys": [_jwk_from_public_key(public_key, kid)]}))

    claims = {
        "iss": "https://evil.example.com/realms/other",
        "aud": "pantry-mcp-connector",
        "sub": "user-1",
        "store_id": ["1"],
        "exp": int(time.time()) + 300,
    }
    token = _sign_token(private_key, kid, claims)

    try:
        await validate_user_token(_settings(), token)
        raise AssertionError("expected JWTValidationError")
    except JWTValidationError:
        pass


@respx.mock
async def test_validate_user_token_rejects_token_without_aud_claim():
    """python-jose silently skips the audience check when `aud` is absent instead
    of rejecting the token (I1) — this must be enforced explicitly."""
    private_key, public_key = _make_rsa_keypair()
    kid = "test-key-1"
    respx.get(
        "https://kc.example.com/realms/restrackit/protocol/openid-connect/certs"
    ).mock(return_value=httpx.Response(200, json={"keys": [_jwk_from_public_key(public_key, kid)]}))

    claims = {
        "iss": "https://kc.example.com/realms/restrackit",
        "sub": "user-1",
        "store_id": ["1"],
        "exp": int(time.time()) + 300,
    }
    token = _sign_token(private_key, kid, claims)

    try:
        await validate_user_token(_settings(), token)
        raise AssertionError("expected JWTValidationError")
    except JWTValidationError:
        pass
