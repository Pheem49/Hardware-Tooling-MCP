"""Hardware Flashing & Toolchain CLI wrappers (Arduino CLI, PlatformIO, ESP-IDF, esptool, Custom CLI)."""

from __future__ import annotations

import getpass
import os
import platform
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer


def _run_cli(
    cmd: list[str],
    cwd: str | None = None,
    timeout_sec: float = 300.0,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a subprocess command safely and return structured stdout/stderr/exit_code."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    start_time = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        duration = round(time.monotonic() - start_time, 2)
        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "command": " ".join(shlex.quote(c) for c in cmd),
            "cwd": cwd or os.getcwd(),
            "duration_sec": duration,
            "stdout": proc.stdout[-15000:] if proc.stdout else "",
            "stderr": proc.stderr[-15000:] if proc.stderr else "",
        }
    except FileNotFoundError as exc:
        return {
            "success": False,
            "exit_code": -1,
            "command": " ".join(shlex.quote(c) for c in cmd),
            "error": f"Executable not found: {cmd[0]} ({exc})",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "exit_code": -2,
            "command": " ".join(shlex.quote(c) for c in cmd),
            "error": f"Command timed out after {timeout_sec}s",
            "stdout": (exc.stdout or "")[-8000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-8000:] if isinstance(exc.stderr, str) else "",
        }


def register_toolchain_tools(mcp: MCPServer) -> None:
    """Register embedded toolchain and firmware flashing tools on the FastMCP instance."""

    @mcp.tool()
    def check_toolchains() -> dict[str, Any]:
        """Check availability and versions of embedded toolchains on the host machine.

        Checks for arduino-cli, pio (PlatformIO), idf.py (ESP-IDF), esptool.py / esptool,
        openocd, dfu-util, avrdude, and picotool.
        """
        candidates = [
            ("arduino-cli", ["arduino-cli", "version"]),
            ("platformio", ["pio", "--version"]),
            ("esp-idf", ["idf.py", "--version"]),
            ("esptool", ["esptool.py", "version"]),
            ("esptool-bin", ["esptool", "version"]),
            ("openocd", ["openocd", "--version"]),
            ("avrdude", ["avrdude", "-?"]),
            ("dfu-util", ["dfu-util", "--version"]),
            ("picotool", ["picotool", "version"]),
        ]
        found: dict[str, Any] = {}
        for name, cmd in candidates:
            binary_path = shutil.which(cmd[0])
            if binary_path:
                res = _run_cli(cmd, timeout_sec=10.0)
                first_line = (res.get("stdout") or res.get("stderr") or "").strip().splitlines()
                found[name] = {
                    "installed": True,
                    "path": binary_path,
                    "version_info": first_line[0] if first_line else "Available",
                }
            else:
                found[name] = {
                    "installed": False,
                    "path": None,
                }
        return {"toolchains": found}

    @mcp.tool()
    def check_prerequisites() -> dict[str, Any]:
        """Run a full host readiness & prerequisite check for hardware tooling.

        Checks:
        1. OS & Serial port permissions (e.g. Linux 'dialout' / 'uucp' / 'plugdev' group membership).
        2. Embedded toolchains (arduino-cli, platformio, esp-idf, esptool, openocd, avrdude, dfu-util, picotool) with install hints.
        3. Host OS & Audio utilities (lsof, arecord, aplay, wpctl, pactl, ffmpeg).
        Returns actionable recommendations so the AI can guide the user if anything is missing.
        """
        sys_name = platform.system()
        user = getpass.getuser()
        recommendations: list[str] = []

        # 1. Check OS & Serial Permissions
        permissions_info: dict[str, Any] = {"os": sys_name, "user": user}
        if sys_name == "Linux":
            user_groups: list[str] = []
            try:
                import grp

                gids = os.getgroups()
                user_groups = [grp.getgrgid(g).gr_name for g in gids]
            except Exception:
                pass

            has_serial_group = any(g in user_groups for g in ("dialout", "uucp"))
            permissions_info["groups"] = user_groups
            permissions_info["serial_permission_ok"] = has_serial_group
            if not has_serial_group:
                recommendations.append(
                    "Linux Serial Port Permission: Current user is not in 'dialout' or 'uucp' group. "
                    "Opening /dev/ttyUSB* or /dev/ttyACM* may fail with 'Permission denied'. "
                    "Fix on Debian/Ubuntu: `sudo usermod -aG dialout $USER` (or `uucp` on Arch), then log out and back in."
                )
        else:
            permissions_info["serial_permission_ok"] = True

        # 2. Check Toolchains + Install Hints
        toolchain_specs = [
            ("arduino-cli", "arduino-cli", "brew install arduino-cli  OR  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh"),
            ("platformio", "pio", "uv tool install platformio  OR  pipx install platformio"),
            ("esptool", "esptool.py", "uv tool install esptool  OR  pip install esptool"),
            ("esp-idf", "idf.py", "Install via ESP-IDF installer or VS Code ESP-IDF extension"),
            ("openocd", "openocd", "sudo apt install openocd  OR  brew install open-ocd"),
            ("avrdude", "avrdude", "sudo apt install avrdude  OR  brew install avrdude"),
            ("dfu-util", "dfu-util", "sudo apt install dfu-util  OR  brew install dfu-util"),
            ("picotool", "picotool", "sudo apt install picotool  OR  brew install picotool"),
        ]
        toolchains_status: dict[str, Any] = {}
        for label, binary, hint in toolchain_specs:
            path = shutil.which(binary) or (shutil.which("esptool") if label == "esptool" else None)
            toolchains_status[label] = {
                "installed": path is not None,
                "path": path,
                "install_hint": None if path else hint,
            }

        if not any(toolchains_status[k]["installed"] for k in ("arduino-cli", "platformio", "esptool", "esp-idf")):
            recommendations.append(
                "No primary MCU flashing toolchain (arduino-cli, platformio, esptool, or esp-idf) was found in PATH. "
                "Install at least one (e.g. `uv tool install platformio` or `uv tool install esptool`)."
            )

        # 3. Check Host OS, Audio, Vision, Logic Analyzer & ADB Utilities
        host_utils = ["lsof", "arecord", "aplay", "wpctl", "pactl", "ffmpeg", "xdotool", "sigrok-cli", "adb"]
        utilities_status = {u: shutil.which(u) is not None for u in host_utils}

        return {
            "ready": permissions_info.get("serial_permission_ok", True),
            "permissions": permissions_info,
            "toolchains": toolchains_status,
            "host_utilities": utilities_status,
            "recommendations": recommendations,
        }

    @mcp.tool()
    def compile_and_flash(
        project_path: str,
        toolchain: str = "auto",
        port: str | None = None,
        board_fqbn_or_env: str | None = None,
        action: str = "compile_and_upload",
        extra_args: list[str] | None = None,
        timeout_sec: float = 300.0,
    ) -> dict[str, Any]:
        """Compile and/or flash firmware to a microcontroller using Arduino CLI, PlatformIO, or ESP-IDF.

        Args:
            project_path: Path to the project directory or sketch file.
            toolchain: 'auto', 'arduino-cli', 'platformio', or 'esp-idf'.
                       When 'auto', detects from platformio.ini, CMakeLists.txt, or .ino files.
            port: Serial port for uploading (e.g., '/dev/ttyUSB0').
            board_fqbn_or_env:
                - For arduino-cli: Board FQBN (e.g., 'esp32:esp32:esp32', 'arduino:avr:uno').
                - For platformio: Environment name (`-e <env>`).
                - For esp-idf: Target chip (e.g., 'esp32', 'esp32s3') if setting target.
            action: 'compile', 'upload', or 'compile_and_upload'.
            extra_args: Optional list of extra CLI flags to append.
            timeout_sec: Maximum execution time in seconds (default 300).
        """
        proj = Path(project_path).expanduser().resolve()
        if not proj.exists():
            return {"success": False, "error": f"Project path does not exist: {proj}"}

        work_dir = str(proj if proj.is_dir() else proj.parent)
        extra = extra_args or []

        # Auto-detect toolchain if requested
        if toolchain == "auto":
            if (Path(work_dir) / "platformio.ini").exists():
                toolchain = "platformio"
            elif (Path(work_dir) / "CMakeLists.txt").exists() and (
                (Path(work_dir) / "sdkconfig").exists() or (Path(work_dir) / "main").is_dir()
            ):
                toolchain = "esp-idf"
            else:
                toolchain = "arduino-cli"

        if toolchain == "arduino-cli":
            if action == "compile":
                cmd = ["arduino-cli", "compile"]
                if board_fqbn_or_env:
                    cmd.extend(["--fqbn", board_fqbn_or_env])
                cmd.extend(extra)
                cmd.append(str(proj))
                return _run_cli(cmd, cwd=work_dir, timeout_sec=timeout_sec)

            elif action == "upload":
                cmd = ["arduino-cli", "upload"]
                if board_fqbn_or_env:
                    cmd.extend(["--fqbn", board_fqbn_or_env])
                if port:
                    cmd.extend(["-p", port])
                cmd.extend(extra)
                cmd.append(str(proj))
                return _run_cli(cmd, cwd=work_dir, timeout_sec=timeout_sec)

            else:  # compile_and_upload
                cmd = ["arduino-cli", "compile", "--upload"]
                if board_fqbn_or_env:
                    cmd.extend(["--fqbn", board_fqbn_or_env])
                if port:
                    cmd.extend(["-p", port])
                cmd.extend(extra)
                cmd.append(str(proj))
                return _run_cli(cmd, cwd=work_dir, timeout_sec=timeout_sec)

        elif toolchain == "platformio":
            cmd = ["pio", "run"]
            if board_fqbn_or_env:
                cmd.extend(["-e", board_fqbn_or_env])
            if action in ("upload", "compile_and_upload"):
                cmd.extend(["-t", "upload"])
            if port:
                cmd.extend(["--upload-port", port])
            cmd.extend(extra)
            return _run_cli(cmd, cwd=work_dir, timeout_sec=timeout_sec)

        elif toolchain == "esp-idf":
            cmd = ["idf.py"]
            if port:
                cmd.extend(["-p", port])
            if action == "compile":
                cmd.append("build")
            elif action == "upload":
                cmd.append("flash")
            else:
                cmd.extend(["build", "flash"])
            cmd.extend(extra)
            return _run_cli(cmd, cwd=work_dir, timeout_sec=timeout_sec)

        else:
            return {
                "success": False,
                "error": f"Unsupported toolchain '{toolchain}'. Choose 'auto', 'arduino-cli', 'platformio', or 'esp-idf'.",
            }

    @mcp.tool()
    def esptool_command(
        operation: str = "chip_id",
        port: str | None = None,
        baudrate: int = 460800,
        chip: str = "auto",
        flash_offset: str = "0x0",
        binary_path: str | None = None,
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run esptool directly to inspect ESP8266/ESP32 chips, read MAC, erase flash, or write raw binary firmware.

        Args:
            operation: 'chip_id', 'flash_id', 'read_mac', 'erase_flash', or 'write_flash'.
            port: Serial port (e.g., '/dev/ttyUSB0').
            baudrate: Baud rate for flashing (default 460800).
            chip: Target chip ('auto', 'esp32', 'esp32s3', 'esp32c3', 'esp8266', etc.).
            flash_offset: Hex address offset when operation='write_flash' (e.g., '0x10000' or '0x0').
            binary_path: Path to .bin file when operation='write_flash'.
            extra_args: Additional arguments passed to esptool.
        """
        exe = shutil.which("esptool.py") or shutil.which("esptool") or "esptool.py"
        cmd = [exe, "--chip", chip]
        if port:
            cmd.extend(["--port", port])
        if baudrate:
            cmd.extend(["--baud", str(baudrate)])

        if operation in ("chip_id", "flash_id", "read_mac", "erase_flash"):
            cmd.append(operation)
        elif operation == "write_flash":
            if not binary_path:
                return {"success": False, "error": "binary_path is required for write_flash"}
            cmd.extend(["write_flash", flash_offset, str(Path(binary_path).expanduser().resolve())])
        else:
            return {
                "success": False,
                "error": f"Unsupported operation '{operation}'. Allowed: chip_id, flash_id, read_mac, erase_flash, write_flash.",
            }

        if extra_args:
            cmd.extend(extra_args)

        return _run_cli(cmd, timeout_sec=180.0)

    @mcp.tool()
    def run_custom_toolchain(
        command: str,
        working_directory: str | None = None,
        timeout_sec: float = 300.0,
    ) -> dict[str, Any]:
        """Run a custom build/flash CLI command (e.g., `make flash`, `west build`, `cargo embed`, `openocd`).

        Args:
            command: Full CLI command string to execute.
            working_directory: Directory where the command should be run.
            timeout_sec: Timeout in seconds (default 300).
        """
        cmd_parts = shlex.split(command)
        if not cmd_parts:
            return {"success": False, "error": "Command cannot be empty."}
        cwd = str(Path(working_directory).expanduser().resolve()) if working_directory else None
        return _run_cli(cmd_parts, cwd=cwd, timeout_sec=timeout_sec)
