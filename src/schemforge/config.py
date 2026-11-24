"""12-Factor Runtime Configuration for SchemForge Production Deployments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    artifacts_dir: Path
    showcase_dir: Path
    static_dir: Path
    host: str
    port: int
    max_api_batch: int
    default_workers: int
    log_level: str


def load_dotenv_file(env_path: Path) -> None:
    """Safely load private key=value pairs from local .env into os.environ without overwriting shell env."""
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[2]
    load_dotenv_file(root / ".env")
    artifacts = Path(os.environ.get("SCHEMFORGE_ARTIFACTS", str(root / "artifacts"))).resolve()
    showcase = Path(os.environ.get("SCHEMFORGE_SHOWCASE", str(root / "showcase"))).resolve()
    static = Path(os.environ.get("SCHEMFORGE_STATIC", str(root / "static"))).resolve()
    cpu_cnt = os.cpu_count() or 2
    return Settings(
        project_root=root,
        artifacts_dir=artifacts,
        showcase_dir=showcase,
        static_dir=static,
        host=os.environ.get("SCHEMFORGE_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", os.environ.get("SCHEMFORGE_PORT", "8765"))),
        max_api_batch=int(os.environ.get("SCHEMFORGE_MAX_API_BATCH", "25000")),
        default_workers=max(1, min(4, int(os.environ.get("SCHEMFORGE_WORKERS", str(max(1, cpu_cnt // 2)))))),
        log_level=os.environ.get("SCHEMFORGE_LOG_LEVEL", "INFO"),
    )
