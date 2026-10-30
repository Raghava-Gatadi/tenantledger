"""Generate local session secrets without overwriting an existing environment."""
import base64
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if not path.exists():
    path.write_text(
        "# Local development only; never commit this file.\n"
        f"SESSION_SECRET={secrets.token_urlsafe(48)}\n"
        f"TOKEN_ENCRYPTION_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}\n"
        "APP_URL=http://localhost:8000\n"
        "OIDC_ISSUER=http://localhost:8080/realms/tenantledger\n"
        "OIDC_CLIENT_SECRET=local-web-client-secret\n"
        "COOKIE_SECURE=false\nENVIRONMENT=development\n"
    )
    path.chmod(0o600)
    print("Generated .env with fresh session and encryption secrets.")
else:
    print("Keeping existing .env.")
