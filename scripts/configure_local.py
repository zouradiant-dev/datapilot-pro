"""Create a private local .env with random role passwords. Refuses overwrites."""

import argparse
import secrets
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url


def role_lines(role: str, url) -> list[str]:
    password = secrets.token_urlsafe(24)
    value = url.set(username="datapilot_" + role, password=password)
    return [
        f"DATAPILOT_{role.upper()}_DATABASE_URL={value.render_as_string(hide_password=False)}",
        f"DATAPILOT_{role.upper()}_PASSWORD={password}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--add-upload-roles", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / ".env"
    if args.add_upload_roles:
        values = dotenv_values(path, interpolate=False)
        url = make_url(values.get("DATAPILOT_ADMIN_DATABASE_URL") or "")
        lines = []
        for role in ("ingest", "upload_reader"):
            keys = [f"DATAPILOT_{role.upper()}_{suffix}" for suffix in ("DATABASE_URL", "PASSWORD")]
            if all(values.get(k) for k in keys):
                continue
            if any(values.get(k) for k in keys):
                raise ValueError("Incomplete upload identity configuration; resolve it manually")
            lines.extend(role_lines(role, url))
        if lines:
            with path.open("a", encoding="utf-8") as output:
                output.write("\n" + "\n".join(lines) + "\n")
        print("Upload identities configured; existing credentials were preserved.")
        return
    password = secrets.token_urlsafe(24)
    url = URL.create(
        "postgresql+psycopg",
        username="postgres",
        password=password,
        host="127.0.0.1",
        port=55432,
        database="datapilot",
    )
    lines = [
        "POSTGRES_DB=datapilot",
        "POSTGRES_USER=postgres",
        "POSTGRES_PORT=55432",
        "POSTGRES_PASSWORD=" + password,
        "DATAPILOT_LLM_MODE=fake",
        "DATAPILOT_ADMIN_DATABASE_URL=" + url.render_as_string(hide_password=False),
    ]
    for role in ("owner", "seed", "reader", "ingest", "upload_reader"):
        lines.extend(role_lines(role, url))
    with path.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    print("Created .env with distinct random credentials; no model API key configured.")


if __name__ == "__main__":
    main()
