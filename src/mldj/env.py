"""Read .env.local without a third-party dependency.

This repo is public. .env.local is gitignored and holds the only two credentials the
project needs: a Spotify client ID and a Last.fm API key.
"""

from pathlib import Path

DEFAULT_ENV_PATH = Path(".env.local")


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines, ignoring blanks and # comments and stripping matched quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Load .env.local if it exists. A missing file is not an error; require() reports it."""
    if not path.exists():
        return {}
    return parse_env(path.read_text(encoding="utf-8"))


def require(env: dict[str, str], key: str) -> str:
    """Fetch a credential, failing with an actionable message when it is missing or blank."""
    value = env.get(key, "")
    if not value:
        raise SystemExit(f"missing {key} - copy .env.local.example to .env.local and fill it in")
    return value
