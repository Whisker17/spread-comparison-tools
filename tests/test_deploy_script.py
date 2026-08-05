"""Sanity checks for scripts/deploy.sh (WHI-849) — no VPS required."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"


def test_deploy_script_exists_and_is_executable() -> None:
    assert DEPLOY_SH.is_file()
    mode = DEPLOY_SH.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/deploy.sh must be executable"


def test_deploy_script_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_deploy_script_requires_deploy_ref() -> None:
    env = os.environ.copy()
    env.pop("DEPLOY_REF", None)
    result = subprocess.run(
        ["bash", str(DEPLOY_SH)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode != 0
    assert "DEPLOY_REF" in result.stderr


def test_deploy_script_dry_run_with_fake_app_dir(tmp_path: Path) -> None:
    """DRY_RUN still needs a git checkout and a secrets file path."""
    app = tmp_path / "app"
    app.mkdir()
    # Minimal git repo so APP_DIR/.git exists.
    subprocess.run(["git", "init"], cwd=app, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=app,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=app,
        check=True,
        capture_output=True,
    )
    (app / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=app, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=app,
        check=True,
        capture_output=True,
    )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=app, text=True
    ).strip()

    secrets = tmp_path / "env"
    secrets.write_text("ETH_RPC_URL=https://example.invalid\n", encoding="utf-8")
    secrets.chmod(0o600)

    host_cfg = tmp_path / "host-config"
    host_cfg.mkdir()
    (host_cfg / "venues.local.yaml").write_text(
        "disabled:\n  - mock\n", encoding="utf-8"
    )

    env = os.environ.copy()
    env.update(
        {
            "DEPLOY_REF": sha,
            "APP_DIR": str(app),
            "ENV_FILE": str(secrets),
            "HOST_CONFIG_DIR": str(host_cfg),
            "REVISION_FILE": str(tmp_path / "deployed-revision"),
            "DRY_RUN": "1",
            "SKIP_RESTART": "1",
        }
    )
    result = subprocess.run(
        ["bash", str(DEPLOY_SH)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "dry-run" in result.stdout.lower() or "DRY_RUN" in result.stdout


def test_dockerfile_skeleton_removed() -> None:
    """Broken template Dockerfile must not remain (WHI-849 / ADR 0002)."""
    assert not (REPO_ROOT / "Dockerfile").exists()
    assert not (REPO_ROOT / "docker-compose.yml").exists()


def test_adr_0002_and_deployment_docs_exist() -> None:
    assert (REPO_ROOT / "docs" / "adr" / "0002-packaging-systemd-uv-venv.md").is_file()
    assert (REPO_ROOT / "docs" / "DEPLOYMENT.md").is_file()
    assert (REPO_ROOT / ".github" / "workflows" / "backend.yml").is_file()
