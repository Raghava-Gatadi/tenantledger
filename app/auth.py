import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Account, WebSession, now

router = APIRouter(prefix="/auth", tags=["identity"])
bearer_scheme = HTTPBearer(auto_error=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cipher() -> Fernet:
    return Fernet(settings().token_encryption_key.encode())


class TokenVerifier:
    def __init__(self):
        self.keys = jwt.PyJWKClient(
            settings().oidc_internal_url + "/protocol/openid-connect/certs",
            cache_jwk_set=True, lifespan=300, timeout=5,
        )

    def decode(self, token: str, audience: str) -> dict:
        try:
            key = self.keys.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token, key, algorithms=["RS256"], audience=audience,
                issuer=settings().oidc_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=2,
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise HTTPException(503, "Identity provider unavailable") from exc
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise HTTPException(401, "Invalid or expired token") from exc

    def verify(self, token: str) -> dict:
        claims = self.decode(token, settings().oidc_audience)
        if claims.get("typ") != "Bearer":
            raise HTTPException(401, "An access token is required")
        # Signature validation alone does not establish current account/session state.
        try:
            response = httpx.post(
                settings().oidc_internal_url + "/protocol/openid-connect/token/introspect",
                auth=(settings().oidc_audience, settings().oidc_api_client_secret),
                data={"token": token}, timeout=5,
            )
            response.raise_for_status()
            active = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Identity provider unavailable") from exc
        if active.get("active") is not True or active.get("sub") != claims["sub"]:
            raise HTTPException(401, "Session is no longer active")
        return claims


@lru_cache
def get_verifier() -> TokenVerifier:
    return TokenVerifier()


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    email: str
    web_session: WebSession | None = None


def account_for_claims(db: Session, claims: dict) -> Account:
    account = db.get(Account, claims["sub"])
    if account is None:
        email = claims.get("email", "").strip().lower()
        if not claims.get("email_verified") or not email or len(email) > 254:
            raise HTTPException(403, "A verified email address is required")
        if db.scalar(select(Account).where(Account.email == email)):
            raise HTTPException(403, "Account linking requires administrator review")
        account = Account(id=claims["sub"], name=claims.get("name", email)[:100], email=email, active=True)
        db.add(account)
        db.flush()
    if not account.active:
        raise HTTPException(401, "Account is disabled")
    return account


def principal(
    request: Request, db: Session = Depends(get_db), verifier: TokenVerifier = Depends(get_verifier),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    authorization = request.headers.get("authorization")
    session = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 16384:
            raise HTTPException(401, "Invalid authorization header")
    else:
        raw_cookie = request.cookies.get("ledger_session", "")
        session = db.get(WebSession, digest(raw_cookie)) if raw_cookie else None
        if not session or session.expires_at <= now():
            raise HTTPException(401, "Sign in to continue")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("origin") != settings().app_url:
                raise HTTPException(403, "Invalid request origin")
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf_token):
                raise HTTPException(403, "Invalid CSRF token")
        try:
            token = cipher().decrypt(session.encrypted_access_token.encode()).decode()
        except InvalidToken as exc:
            raise HTTPException(401, "Invalid session") from exc
    claims = verifier.verify(token)
    if session and session.user_id != claims["sub"]:
        raise HTTPException(401, "Invalid session identity")
    account = account_for_claims(db, claims)
    return Principal(account.id, account.name, account.email, session)


@router.get("/login")
def login():
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    payload = URLSafeTimedSerializer(settings().session_secret, salt="oidc-login").dumps(
        {"state": state, "nonce": nonce, "verifier": verifier}
    )
    query = urlencode({
        "client_id": settings().oidc_client_id, "response_type": "code",
        "redirect_uri": settings().app_url + "/auth/callback", "scope": "openid profile email",
        "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
    })
    response = RedirectResponse(settings().oidc_issuer + "/protocol/openid-connect/auth?" + query)
    response.set_cookie("ledger_login", payload, httponly=True, secure=settings().cookie_secure,
                        samesite="lax", max_age=300, path="/auth")
    return response


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "",
             db: Session = Depends(get_db), verifier: TokenVerifier = Depends(get_verifier)):
    try:
        flow = URLSafeTimedSerializer(settings().session_secret, salt="oidc-login").loads(
            request.cookies.get("ledger_login", ""), max_age=300,
        )
    except BadSignature as exc:
        raise HTTPException(400, "Login expired; start again") from exc
    if not code or not secrets.compare_digest(state, flow["state"]):
        raise HTTPException(400, "Invalid login state")
    try:
        result = httpx.post(
            settings().oidc_internal_url + "/protocol/openid-connect/token",
            auth=(settings().oidc_client_id, settings().oidc_client_secret), timeout=5,
            data={"grant_type": "authorization_code", "code": code,
                  "redirect_uri": settings().app_url + "/auth/callback", "code_verifier": flow["verifier"]},
        )
        result.raise_for_status()
        tokens = result.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(400, "Login exchange failed; start again") from exc
    identity = verifier.decode(tokens["id_token"], settings().oidc_client_id)
    if not secrets.compare_digest(identity.get("nonce", ""), flow["nonce"]):
        raise HTTPException(400, "Invalid login nonce")
    claims = verifier.verify(tokens["access_token"])
    if claims["sub"] != identity["sub"]:
        raise HTTPException(400, "Login identity mismatch")
    account = account_for_claims(db, claims)
    raw = secrets.token_urlsafe(48)
    # Rotate any existing browser session and opportunistically remove expired rows.
    previous = request.cookies.get("ledger_session", "")
    db.execute(delete(WebSession).where(WebSession.expires_at <= now()))
    if previous:
        db.execute(delete(WebSession).where(WebSession.id_hash == digest(previous)))
    expiry = min(claims["exp"], int(now().timestamp()) + settings().session_max_seconds)
    db.add(WebSession(
        id_hash=digest(raw), user_id=account.id,
        encrypted_access_token=cipher().encrypt(tokens["access_token"].encode()).decode(),
        encrypted_id_token=cipher().encrypt(tokens["id_token"].encode()).decode(),
        csrf_token=secrets.token_urlsafe(32), expires_at=datetime.fromtimestamp(expiry, UTC),
    ))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("ledger_login", path="/auth")
    response.set_cookie("ledger_session", raw, httponly=True, secure=settings().cookie_secure,
                        samesite="lax", max_age=max(1, expiry - int(now().timestamp())), path="/")
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    # Local logout must work even after the IdP session/token has expired.
    raw = request.cookies.get("ledger_session", "")
    session = db.get(WebSession, digest(raw)) if raw else None
    params = {"client_id": settings().oidc_client_id, "post_logout_redirect_uri": settings().app_url + "/"}
    if session:
        if request.headers.get("origin") != settings().app_url or not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf_token,
        ):
            raise HTTPException(403, "Invalid logout request")
        params["id_token_hint"] = cipher().decrypt(session.encrypted_id_token.encode()).decode()
        db.delete(session)
    from fastapi.responses import JSONResponse
    response = JSONResponse({"redirect": settings().oidc_issuer + "/protocol/openid-connect/logout?" + urlencode(params)})
    response.delete_cookie("ledger_session", path="/")
    return response
