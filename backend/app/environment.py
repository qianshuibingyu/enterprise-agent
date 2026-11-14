"""Environment loading helpers for host-side backend commands."""

import os
from pathlib import Path


def load_project_env(env_path: Path | None = None) -> None:
    """Load repository-root ``.env`` values that are not already exported.

    Docker Compose passes these values to the backend container. Direct host
    commands, including Alembic, need the same configuration source without
    logging its values.
    """
    env_path = env_path or Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        raw_name, separator, value = line.partition("=")
        name = raw_name.strip()
        if not separator or not name or not name.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)
