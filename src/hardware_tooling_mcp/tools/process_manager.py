"""Host OS Process & Serial Port Lock Management tools."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
from mcp.server.mcpserver import MCPServer

# Registry of background processes launched by this MCP server session
_MANAGED_PROCESSES: dict[int, subprocess.Popen[str]] = {}


def _find_pids_holding_port(port: str) -> list[dict[str, Any]]:
    """Find processes that have the specified device file open."""
    resolved_port = str(Path(port).resolve()) if os.path.exists(port) else port
    holders: dict[int, dict[str, Any]] = {}

    # Method 1: Use lsof if available (fast & accurate on Linux/macOS)
    if shutil.which("lsof"):
        try:
            proc = subprocess.run(
                ["lsof", "-F", "pcn", port],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            current_pid: int | None = None
            current_cmd: str = ""
            for line in proc.stdout.splitlines():
                if line.startswith("p"):
                    current_pid = int(line[1:])
                elif line.startswith("c"):
                    current_cmd = line[1:]
                elif line.startswith("n") and current_pid is not None:
                    try:
                        p = psutil.Process(current_pid)
                        holders[current_pid] = {
                            "pid": current_pid,
                            "name": p.name(),
                            "cmdline": " ".join(p.cmdline()),
                            "status": p.status(),
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        holders[current_pid] = {
                            "pid": current_pid,
                            "name": current_cmd,
                            "cmdline": current_cmd,
                            "status": "unknown",
                        }
        except Exception:
            pass

    # Method 2: Scan /proc/<pid>/fd for symlinks to the serial port on Linux
    proc_root = Path("/proc")
    if proc_root.is_dir():
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid in holders:
                continue
            fd_dir = entry / "fd"
            try:
                if not fd_dir.is_dir():
                    continue
                for fd in fd_dir.iterdir():
                    try:
                        target = os.readlink(fd)
                        if target in (port, resolved_port):
                            p = psutil.Process(pid)
                            holders[pid] = {
                                "pid": pid,
                                "name": p.name(),
                                "cmdline": " ".join(p.cmdline()),
                                "status": p.status(),
                            }
                            break
                    except OSError:
                        continue
            except (PermissionError, OSError, psutil.Error):
                continue

    return list(holders.values())


def register_process_tools(mcp: MCPServer) -> None:
    """Register Host Process and Port Lock tools on the FastMCP instance."""

    @mcp.tool()
    def list_processes(
        filter_name: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List running OS processes, optionally filtered by process name or command line.

        Useful for checking if IDE serial monitors, minicom, screen, openocd, gdb, or
        emulators are running.

        Args:
            filter_name: Case-insensitive substring to match against process name or cmdline.
            limit: Maximum number of processes to return (default 50).
        """
        matched: list[dict[str, Any]] = []
        needle = filter_name.lower() if filter_name else None

        for proc in psutil.process_iter(["pid", "name", "username", "status", "cmdline", "cpu_percent", "memory_info"]):
            try:
                info = proc.info
                name = info.get("name") or ""
                cmdline_list = info.get("cmdline") or []
                cmdline_str = " ".join(cmdline_list)

                if needle and needle not in name.lower() and needle not in cmdline_str.lower():
                    continue

                mem_mb = round((info["memory_info"].rss / (1024 * 1024)), 2) if info.get("memory_info") else 0.0
                matched.append(
                    {
                        "pid": info["pid"],
                        "name": name,
                        "status": info.get("status"),
                        "user": info.get("username"),
                        "memory_mb": mem_mb,
                        "cmdline": cmdline_str[:300],
                    }
                )
                if len(matched) >= limit:
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "count": len(matched),
            "filter": filter_name,
            "processes": matched,
        }

    @mcp.tool()
    def find_port_occupiers(port: str) -> dict[str, Any]:
        """Check which processes are currently locking/using a serial port (e.g. '/dev/ttyUSB0').

        Use this when you encounter 'Port busy' or 'Resource temporarily unavailable' errors.
        """
        holders = _find_pids_holding_port(port)
        return {
            "port": port,
            "is_busy": len(holders) > 0,
            "occupying_processes": holders,
        }

    @mcp.tool()
    def free_serial_port(port: str, force: bool = False) -> dict[str, Any]:
        """Terminate processes that are locking a serial port so it can be used for flashing or monitoring.

        Args:
            port: Device path (e.g., '/dev/ttyUSB0' or '/dev/ttyACM0').
            force: Send SIGKILL instead of SIGTERM if true.
        """
        holders = _find_pids_holding_port(port)
        if not holders:
            return {
                "success": True,
                "port": port,
                "message": "No processes found holding this serial port.",
                "terminated": [],
            }

        terminated: list[dict[str, Any]] = []
        errors: list[str] = []
        sig = signal.SIGKILL if force else signal.SIGTERM

        for h in holders:
            pid = h["pid"]
            try:
                p = psutil.Process(pid)
                p.send_signal(sig)
                terminated.append(h)
            except Exception as exc:
                errors.append(f"PID {pid} ({h.get('name')}): {exc}")

        time.sleep(0.3)
        remaining = _find_pids_holding_port(port)

        return {
            "success": len(remaining) == 0,
            "port": port,
            "terminated": terminated,
            "remaining_occupiers": remaining,
            "errors": errors,
        }

    @mcp.tool()
    def start_process(
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        background: bool = False,
        timeout_sec: float = 15.0,
    ) -> dict[str, Any]:
        """Start an application or CLI utility on the host machine.

        Args:
            command: Executable name or full command line string.
            args: Optional list of arguments (if not already in `command`).
            cwd: Optional working directory.
            background: If True, runs the process in the background and returns its PID immediately.
            timeout_sec: When background=False, wait up to this many seconds for completion.
        """
        if os.path.exists(command):
            cmd_list = [command]
        else:
            cmd_list = shlex.split(command)
        if args:
            cmd_list.extend(args)
        if not cmd_list:
            return {"success": False, "error": "Empty command"}

        work_dir = str(Path(cwd).expanduser().resolve()) if cwd else None

        try:
            if background:
                proc = subprocess.Popen(
                    cmd_list,
                    cwd=work_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                _MANAGED_PROCESSES[proc.pid] = proc
                time.sleep(0.2)
                poll = proc.poll()
                return {
                    "success": poll is None or poll == 0,
                    "background": True,
                    "pid": proc.pid,
                    "command": " ".join(shlex.quote(x) for x in cmd_list),
                    "running": poll is None,
                    "exit_code": poll,
                }
            else:
                completed = subprocess.run(
                    cmd_list,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    check=False,
                )
                return {
                    "success": completed.returncode == 0,
                    "background": False,
                    "exit_code": completed.returncode,
                    "command": " ".join(shlex.quote(x) for x in cmd_list),
                    "stdout": completed.stdout[-10000:] if completed.stdout else "",
                    "stderr": completed.stderr[-10000:] if completed.stderr else "",
                }
        except Exception as exc:
            return {
                "success": False,
                "command": " ".join(shlex.quote(x) for x in cmd_list),
                "error": str(exc),
            }

    @mcp.tool()
    def kill_process(
        pid: int | None = None,
        process_name: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Stop/terminate a running process by PID or by process name.

        Args:
            pid: Specific Process ID to kill.
            process_name: Name of the process to kill (if pid is not specified).
            force: Use SIGKILL (force kill) instead of graceful SIGTERM.
        """
        if pid is None and not process_name:
            return {"success": False, "error": "Provide either `pid` or `process_name`."}

        sig = signal.SIGKILL if force else signal.SIGTERM
        killed: list[dict[str, Any]] = []
        errors: list[str] = []

        targets: list[psutil.Process] = []
        if pid is not None:
            try:
                targets.append(psutil.Process(pid))
            except psutil.NoSuchProcess:
                return {"success": False, "error": f"No process found with PID {pid}"}
        elif process_name:
            needle = process_name.lower()
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if p.info["name"] and needle == p.info["name"].lower():
                        targets.append(p)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if not targets:
            return {"success": False, "error": f"No matching processes found for '{process_name}'."}

        for p in targets:
            try:
                p_info = {"pid": p.pid, "name": p.name()}
                p.send_signal(sig)
                _MANAGED_PROCESSES.pop(p.pid, None)
                killed.append(p_info)
            except Exception as exc:
                errors.append(f"PID {p.pid}: {exc}")

        return {
            "success": len(killed) > 0 and len(errors) == 0,
            "signal": "SIGKILL" if force else "SIGTERM",
            "killed": killed,
            "errors": errors,
        }
