from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(
    os.environ.get(
        "POS_PROJECT_ROOT",
        str(Path(__file__).resolve().parent.parent),
    )
).resolve()

mcp = FastMCP("POS Project Diagnostics")

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".tox",
    ".probe",
    ".e2e-real",
    ".migration-validation",
    ".kilo",
}

ALLOWED_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".yaml",
    ".yml",
    ".bat",
    ".html",
    ".css",
    ".js",
    ".env.example",
}

BLOCKED_NAMES = {".env"}

MAX_READ_BYTES = 512 * 1024
PYTEST_TIMEOUT_SECONDS = 120
COMMAND_TIMEOUT_SECONDS = 30


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _resolve_project_path(user_path: str | None) -> Path:
    if not user_path:
        return PROJECT_ROOT
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate = candidate.resolve()
    if not _is_relative_to(candidate, PROJECT_ROOT):
        raise ValueError(f"Path outside project root: {candidate}")
    if _is_excluded(candidate.relative_to(PROJECT_ROOT)):
        raise ValueError(f"Path is in an excluded directory: {candidate}")
    return candidate


def _is_allowed_file(path: Path) -> bool:
    if path.name in BLOCKED_NAMES:
        return False
    return path.suffix in ALLOWED_EXTENSIONS


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git executable not found on PATH.")
    return subprocess.run(
        [git, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )


@mcp.tool()
def project_info() -> dict[str, Any]:
    """Return project root, Python interpreter, and interpreter version."""
    return {
        "project_root": str(PROJECT_ROOT),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "python_version_info": ".".join(map(str, sys.version_info[:3])),
    }


@mcp.tool()
def list_project_files(subpath: str = "", max_entries: int = 200) -> dict[str, Any]:
    """List files and directories under the project root (or a subpath).

    Excluded directories (venv, .git, __pycache__, etc.) are skipped.
    """
    target = _resolve_project_path(subpath)
    if not target.exists():
        return {"error": f"Not found: {target}", "entries": []}
    if not target.is_dir():
        return {"error": f"Not a directory: {target}", "entries": []}

    entries: list[dict[str, Any]] = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.name in EXCLUDED_DIRS or item.name in BLOCKED_NAMES:
            continue
        rel = item.relative_to(PROJECT_ROOT).as_posix()
        if item.is_dir():
            entries.append({"type": "dir", "path": rel})
        elif _is_allowed_file(item):
            entries.append({"type": "file", "path": rel, "size": item.stat().st_size})
        if len(entries) >= max_entries:
            break

    return {
        "root": str(PROJECT_ROOT),
        "subpath": target.relative_to(PROJECT_ROOT).as_posix() if target != PROJECT_ROOT else ".",
        "count": len(entries),
        "truncated": len(entries) >= max_entries,
        "entries": entries,
    }


@mcp.tool()
def read_project_file(path: str) -> dict[str, Any]:
    """Read a single allowed project file (text, size-limited)."""
    target = _resolve_project_path(path)
    if not target.exists() or not target.is_file():
        return {"error": f"File not found: {target}"}
    if not _is_allowed_file(target):
        return {"error": f"File type not allowed: {target.suffix or target.name}"}
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        return {"error": f"File too large ({size} bytes > {MAX_READ_BYTES})."}
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"Read failed: {exc}"}
    return {
        "path": target.relative_to(PROJECT_ROOT).as_posix(),
        "size": size,
        "content": content,
    }


@mcp.tool()
def search_project(
    query: str,
    pattern: str = "**/*.py",
    max_results: int = 100,
) -> dict[str, Any]:
    """Search for a text query in project files matching a glob pattern.

    Use this to find function names, symbols, or text across the codebase.
    """
    if not query:
        return {"error": "Query must not be empty.", "matches": []}

    results: list[dict[str, Any]] = []
    query_lower = query.lower()
    for path in PROJECT_ROOT.rglob(pattern):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if _is_excluded(rel) or not _is_allowed_file(path):
            continue
        try:
            if path.stat().st_size > MAX_READ_BYTES:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            if query_lower in line.lower():
                results.append(
                    {
                        "file": rel.as_posix(),
                        "line": lineno,
                        "text": line.strip()[:200],
                    }
                )
                if len(results) >= max_results:
                    return {
                        "query": query,
                        "pattern": pattern,
                        "truncated": True,
                        "count": len(results),
                        "matches": results,
                    }
    return {
        "query": query,
        "pattern": pattern,
        "truncated": False,
        "count": len(results),
        "matches": results,
    }


@mcp.tool()
def check_python_syntax(path: str = "") -> dict[str, Any]:
    """Check Python syntax with ast.parse for one file or all project .py files."""
    if path:
        targets = [_resolve_project_path(path)]
        if targets[0].is_dir():
            targets = [
                p
                for p in targets[0].rglob("*.py")
                if not _is_excluded(p.relative_to(PROJECT_ROOT))
            ]
    else:
        targets = [
            p
            for p in PROJECT_ROOT.rglob("*.py")
            if not _is_excluded(p.relative_to(PROJECT_ROOT))
        ]

    errors: list[dict[str, str]] = []
    checked = 0
    for file_path in targets:
        if not file_path.is_file():
            continue
        checked += 1
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(
                {"file": file_path.relative_to(PROJECT_ROOT).as_posix(), "error": str(exc)}
            )
            continue
        try:
            ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            errors.append(
                {
                    "file": file_path.relative_to(PROJECT_ROOT).as_posix(),
                    "line": str(exc.lineno or "?"),
                    "error": exc.msg,
                }
            )
    return {"checked": checked, "error_count": len(errors), "errors": errors}


@mcp.tool()
def environment_report() -> dict[str, Any]:
    """Report Python environment details and key installed dependencies."""
    packages: dict[str, str] = {}
    for name in (
        "mcp",
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "alembic",
        "pydantic",
        "pytest",
        "requests",
        "cryptography",
        "pillow",
        "openpyxl",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"

    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": sys.platform,
        "in_virtualenv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "project_root": str(PROJECT_ROOT),
        "pytest_available": importlib.util.find_spec("pytest") is not None,
        "packages": packages,
    }


@mcp.tool()
def run_pytest(target: str = "tests", timeout_seconds: int = PYTEST_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run pytest on a target path with a hard timeout. No free-form shell."""
    if importlib.util.find_spec("pytest") is None:
        return {"error": "pytest is not installed in this environment."}

    timeout = max(10, min(timeout_seconds, 300))
    resolved = _resolve_project_path(target)
    if not resolved.exists():
        return {"error": f"Target not found: {target}"}

    cmd = [sys.executable, "-m", "pytest", str(resolved), "-q", "--tb=short"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,  # jangan warisi pipe stdin MCP
        )
    except subprocess.TimeoutExpired:
        return {"error": f"pytest timed out after {timeout}s.", "timeout": True}

    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
        "timeout": False,
    }


@mcp.tool()
def git_status() -> dict[str, Any]:
    """Show short git status and the last few commits, if Git is available."""
    if shutil.which("git") is None:
        return {"error": "Git is not installed or not on PATH."}

    try:
        status = _run_git(["status", "--short"])
        log = _run_git(["log", "--oneline", "-10"])
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    except (subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
        return {"error": str(exc)}

    return {
        "branch": branch.stdout.strip() if branch.returncode == 0 else "unknown",
        "status": status.stdout.strip() if status.returncode == 0 else status.stderr.strip(),
        "recent_commits": log.stdout.strip() if log.returncode == 0 else log.stderr.strip(),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
