"""Kernel Host Sandboxing for Stage 3 Agent Execution (macOS sandbox-exec & Linux bwrap)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

CREDENTIAL_REL_DIRS: tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".config/gh",
    ".config/gcloud",
    ".kube",
    ".azure",
)


class SandboxUnavailableError(RuntimeError):
    """Raised when --sandbox-policy=required cannot establish OS kernel process isolation."""


@dataclass(frozen=True)
class SandboxCapability:
    """Detected OS kernel sandbox backend and nesting state."""

    backend: str  # "macos-seatbelt" | "linux-bwrap" | "none"
    available: bool
    outer_sandbox_detected: bool
    binary_path: str | None
    reason: str


@dataclass(frozen=True)
class SandboxPlan:
    """Materialized command wrapper and audit evidence for Stage 3 host-agent execution."""

    backend: str
    enforced: bool
    outer_sandbox_detected: bool
    command: list[str]
    profile_text: str | None
    cleanup_paths: tuple[Path, ...]


def _escape_sbpl_path(path: Path) -> str:
    raw = str(path.resolve())
    return raw.replace("\\", "\\\\").replace('"', '\\"')


def build_macos_seatbelt_profile(
    workspace_dir: Path,
    *,
    allow_network: bool = False,
    extra_writable_paths: Sequence[Path] = (),
    home_dir: Path | None = None,
) -> str:
    """
    Build a macOS XNU Seatbelt (sandbox-exec) profile enforcing Pattern MCP-002 & MCP-008:
    1. Denies reads/writes to sensitive user credential stores (~/.ssh, ~/.aws, ~/.config/gh, etc.).
    2. Denies file writes globally across the host filesystem.
    3. Permits temporary scratch outside workspace_dir, then re-locks workspace_dir read-only.
    4. Carves out write access strictly to src/tools/, tests/unit/, and README.md.
    """
    ws = workspace_dir.resolve()
    sys_tmp = Path(tempfile.gettempdir()).resolve()
    user_home = (home_dir or Path.home()).resolve()

    cred_clauses = "\n".join(
        f'  (subpath "{_escape_sbpl_path(user_home / rel)}")' for rel in CREDENTIAL_REL_DIRS
    )

    extra_clauses: list[str] = []
    for extra in extra_writable_paths:
        resolved_extra = extra.resolve()
        if not resolved_extra.is_relative_to(ws):
            extra_clauses.append(f'  (subpath "{_escape_sbpl_path(resolved_extra)}")')

    net_rule = (
        ";; Network access explicitly permitted by caller"
        if allow_network
        else "(deny network*)"
    )

    lines = [
        "(version 1)",
        "(allow default)",
        net_rule,
        ";; Block host credential stores from untrusted agent reads/writes",
        "(deny file-read* file-write*",
        cred_clauses + ")",
        ";; Deny all host filesystem writes by default",
        "(deny file-write*)",
        ";; Allow ephemeral scratch outside the locked workspace",
        "(allow file-write*",
        '  (literal "/dev/null")',
        '  (literal "/dev/zero")',
        '  (subpath "/private/tmp")',
        '  (subpath "/tmp")',
        f'  (subpath "{_escape_sbpl_path(sys_tmp)}")',
        *extra_clauses,
        ")",
        ";; Re-lock the forged workspace (protects locked files even if workspace is under /tmp)",
        f'(deny file-write* (subpath "{_escape_sbpl_path(ws)}"))',
        ";; Grant write access ONLY to the 3 agent-writable targets (MCP-002 / NIST CM-5 & SC-39)",
        "(allow file-write*",
        f'  (subpath "{_escape_sbpl_path(ws / "src" / "tools")}")',
        f'  (subpath "{_escape_sbpl_path(ws / "tests" / "unit")}")',
        f'  (literal "{_escape_sbpl_path(ws / "README.md")}"))',
        "",
    ]
    return "\n".join(lines)


def build_linux_bwrap_command(
    inner_cmd: Sequence[str],
    workspace_dir: Path,
    *,
    bwrap_bin: str = "bwrap",
    allow_network: bool = False,
    extra_writable_paths: Sequence[Path] = (),
    home_dir: Path | None = None,
) -> list[str]:
    """
    Build a Linux bubblewrap (bwrap) namespace command enforcing Pattern MCP-002 & MCP-008:
    - Mounts host root read-only (--ro-bind / /).
    - Masks sensitive user credential directories with empty tmpfs mounts.
    - Mounts workspace_dir read-only, overlaying ONLY src/tools/, tests/unit/, and README.md rw.
    """
    ws = workspace_dir.resolve()
    user_home = (home_dir or Path.home()).resolve()

    cmd: list[str] = [
        bwrap_bin,
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",  # noqa: S108
    ]
    if not allow_network:
        cmd.append("--unshare-net")

    for rel in CREDENTIAL_REL_DIRS:
        cred_dir = user_home / rel
        if cred_dir.is_dir():
            cmd.extend(["--tmpfs", str(cred_dir)])

    sys_tmp = Path("/tmp").resolve()  # noqa: S108
    for tok in inner_cmd:
        cand = Path(tok)
        if cand.exists():
            res_cand = cand.resolve()
            if res_cand.is_relative_to(sys_tmp) and not res_cand.is_relative_to(ws):
                cmd.extend(["--ro-bind", str(res_cand), str(res_cand)])

    for extra in extra_writable_paths:
        resolved_extra = extra.resolve()
        if resolved_extra.exists() and not resolved_extra.is_relative_to(ws):
            cmd.extend(["--bind", str(resolved_extra), str(resolved_extra)])

    readme = ws / "README.md"
    readme.touch(exist_ok=True)
    (ws / "src" / "tools").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "unit").mkdir(parents=True, exist_ok=True)

    cmd.extend(
        [
            "--ro-bind",
            str(ws),
            str(ws),
            "--bind",
            str(ws / "src" / "tools"),
            str(ws / "src" / "tools"),
            "--bind",
            str(ws / "tests" / "unit"),
            str(ws / "tests" / "unit"),
            "--bind",
            str(readme),
            str(readme),
            "--chdir",
            str(ws),
            "--",
            *list(inner_cmd),
        ]
    )
    return cmd


def probe_kernel_sandbox_capability(platform_override: str | None = None) -> SandboxCapability:
    """Empirically probe whether XNU sandbox-exec or Linux bwrap can launch on this host."""
    plat = platform_override or sys.platform

    if plat == "darwin":
        sb_bin = shutil.which("sandbox-exec") or (
            "/usr/bin/sandbox-exec" if Path("/usr/bin/sandbox-exec").is_file() else None
        )
        true_bin = shutil.which("true") or "/usr/bin/true"
        if not sb_bin:
            return SandboxCapability(
                backend="none",
                available=False,
                outer_sandbox_detected=False,
                binary_path=None,
                reason="macOS sandbox-exec binary not found",
            )
        proc = subprocess.run(  # noqa: S603
            [sb_bin, "-p", "(version 1)(allow default)", true_bin],
            text=True,
            capture_output=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode == 0:
            return SandboxCapability(
                backend="macos-seatbelt",
                available=True,
                outer_sandbox_detected=False,
                binary_path=sb_bin,
                reason="XNU sandbox-exec seatbelt verified",
            )
        stderr_low = (proc.stderr or "").lower()
        outer = "sandbox_apply" in stderr_low and "operation not permitted" in stderr_low
        return SandboxCapability(
            backend="macos-seatbelt",
            available=False,
            outer_sandbox_detected=outer,
            binary_path=sb_bin,
            reason=(
                "Parent process already confined inside outer XNU Seatbelt sandbox"
                if outer
                else f"sandbox-exec probe exited {proc.returncode}: {proc.stderr.strip()}"
            ),
        )

    if plat.startswith("linux"):
        bw_bin = shutil.which("bwrap")
        true_bin = shutil.which("true") or "/bin/true"
        if not bw_bin:
            return SandboxCapability(
                backend="none",
                available=False,
                outer_sandbox_detected=False,
                binary_path=None,
                reason="Linux bubblewrap (bwrap) binary not installed",
            )
        proc = subprocess.run(  # noqa: S603
            [bw_bin, "--ro-bind", "/", "/", "--", true_bin],
            text=True,
            capture_output=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode == 0:
            return SandboxCapability(
                backend="linux-bwrap",
                available=True,
                outer_sandbox_detected=False,
                binary_path=bw_bin,
                reason="Linux bubblewrap user/mount namespaces verified",
            )
        stderr_low = (proc.stderr or "").lower()
        outer = "operation not permitted" in stderr_low or "permission denied" in stderr_low
        return SandboxCapability(
            backend="linux-bwrap",
            available=False,
            outer_sandbox_detected=outer,
            binary_path=bw_bin,
            reason=(
                "Unprivileged namespace creation restricted by outer container/LSM policy"
                if outer
                else f"bwrap probe exited {proc.returncode}: {proc.stderr.strip()}"
            ),
        )

    return SandboxCapability(
        backend="none",
        available=False,
        outer_sandbox_detected=False,
        binary_path=None,
        reason=f"Unsupported kernel sandbox platform: {plat}",
    )


def prepare_sandboxed_agent_command(
    inner_cmd: Sequence[str],
    workspace_dir: Path,
    *,
    policy: str = "auto",
    allow_network: bool = False,
    extra_writable_paths: Sequence[Path] = (),
    capability: SandboxCapability | None = None,
) -> SandboxPlan:
    """Wrap a host-agent command in XNU Seatbelt or Linux bubblewrap per sandbox policy."""
    if policy not in {"auto", "required", "off"}:
        raise ValueError(f"Unsupported sandbox policy {policy!r}; expected auto|required|off.")

    if policy == "off":
        return SandboxPlan(
            backend="disabled",
            enforced=False,
            outer_sandbox_detected=False,
            command=list(inner_cmd),
            profile_text=None,
            cleanup_paths=(),
        )

    cap = capability or probe_kernel_sandbox_capability()

    if cap.available and cap.backend == "macos-seatbelt" and cap.binary_path:
        ws = workspace_dir.resolve()
        (ws / "README.md").touch(exist_ok=True)
        profile_text = build_macos_seatbelt_profile(
            ws,
            allow_network=allow_network,
            extra_writable_paths=extra_writable_paths,
        )
        fd, raw_tmp = tempfile.mkstemp(prefix="forge-seatbelt-", suffix=".sb")
        import os

        os.close(fd)
        profile_path = Path(raw_tmp)
        profile_path.write_text(profile_text, encoding="utf-8")
        return SandboxPlan(
            backend="macos-seatbelt",
            enforced=True,
            outer_sandbox_detected=False,
            command=[cap.binary_path, "-f", str(profile_path), *list(inner_cmd)],
            profile_text=profile_text,
            cleanup_paths=(profile_path,),
        )

    if cap.available and cap.backend == "linux-bwrap" and cap.binary_path:
        bwrap_cmd = build_linux_bwrap_command(
            inner_cmd,
            workspace_dir,
            bwrap_bin=cap.binary_path,
            allow_network=allow_network,
            extra_writable_paths=extra_writable_paths,
        )
        return SandboxPlan(
            backend="linux-bwrap",
            enforced=True,
            outer_sandbox_detected=False,
            command=bwrap_cmd,
            profile_text=None,
            cleanup_paths=(),
        )

    if policy == "required" and not cap.outer_sandbox_detected:
        raise SandboxUnavailableError(
            f"Kernel host sandboxing required (NIST SC-39) but unavailable: {cap.reason}"
        )

    return SandboxPlan(
        backend=f"outer-{cap.backend}" if cap.outer_sandbox_detected else "file-mode-sha256",
        enforced=cap.outer_sandbox_detected,
        outer_sandbox_detected=cap.outer_sandbox_detected,
        command=list(inner_cmd),
        profile_text=None,
        cleanup_paths=(),
    )
