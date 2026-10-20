"""Create a private local .env with random role passwords. Refuses overwrites."""

import secrets
from pathlib import Path

from sqlalchemy.engine import URL

root = Path(__file__).resolve().parents[1]
passwords = {role: secrets.token_urlsafe(24) for role in ("admin", "owner", "seed", "reader")}
lines = [
    "POSTGRES_DB=datapilot",
    "POSTGRES_USER=postgres",
    "POSTGRES_PORT=55432",
    "POSTGRES_PASSWORD=" + passwords["admin"],
    "DATAPILOT_LLM_MODE=fake",
]
for role, password in passwords.items():
    user = "postgres" if role == "admin" else "datapilot_" + role
    url = URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host="127.0.0.1",
        port=55432,
        database="datapilot",
    )
    lines.append(
        f"DATAPILOT_{role.upper()}_DATABASE_URL={url.render_as_string(hide_password=False)}"
    )
    if role != "admin":
        lines.append(f"DATAPILOT_{role.upper()}_PASSWORD={password}")
with (root / ".env").open("x", encoding="utf-8") as output:
    output.write("\n".join(lines) + "\n")
print("Created .env with distinct random credentials; no model API key configured.")
