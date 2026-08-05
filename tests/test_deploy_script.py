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


def _init_git_app(app: Path) -> str:
    app.mkdir(parents=True, exist_ok=True)
    (app / "config").mkdir(exist_ok=True)
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
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=app, text=True
    ).strip()


def test_deploy_script_fails_when_health_never_ok(tmp_path: Path) -> None:
    """AC: non-zero exit when /health never becomes healthy (WHI-849)."""
    app = tmp_path / "app"
    sha = _init_git_app(app)
    secrets = tmp_path / "env"
    secrets.write_text("ETH_RPC_URL=https://example.invalid\n", encoding="utf-8")
    secrets.chmod(0o600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Fake systemctl / uv / curl so the script reaches the health gate offline.
    (bin_dir / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "uv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "curl").write_text(
        "#!/bin/sh\n"
        "# emulate: curl -sS -o FILE -w '%{http_code}' --max-time N URL\n"
        "out=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then out=$2; shift 2; continue; fi\n"
        "  if [ \"$1\" = \"-w\" ] || [ \"$1\" = \"--max-time\" ]; then shift 2; continue; fi\n"
        "  if [ \"$1\" = \"-sS\" ]; then shift; continue; fi\n"
        "  shift\n"
        "done\n"
        "if [ -n \"$out\" ]; then printf '%s\\n' '{\"status\":\"down\"}' >\"$out\"; fi\n"
        "printf '503'\n",
        encoding="utf-8",
    )
    for name in ("systemctl", "uv", "curl"):
        (bin_dir / name).chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "DEPLOY_REF": sha,
            "APP_DIR": str(app),
            "ENV_FILE": str(secrets),
            "HOST_CONFIG_DIR": str(tmp_path / "missing-host-config"),
            "REVISION_FILE": str(tmp_path / "deployed-revision"),
            "HEALTH_URL": "http://127.0.0.1:9/health",
            "HEALTH_TIMEOUT_SEC": "2",
            "DRY_RUN": "0",
            "SKIP_RESTART": "0",
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
    assert result.returncode != 0, result.stdout + result.stderr
    assert "unhealthy" in (result.stderr + result.stdout).lower()
    assert not (tmp_path / "deployed-revision").exists()
