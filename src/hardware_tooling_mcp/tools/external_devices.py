"""Webcam/USB Microscope Vision, Logic Analyzer (sigrok-cli), and Android (ADB) hardware tools."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer


def register_external_device_tools(mcp: MCPServer) -> None:
    """Register Webcam/Microscope, Logic Analyzer (sigrok-cli), and Android ADB tools."""

    # =========================================================================
    # 1. Webcam / USB Microscope Hardware Vision
    # =========================================================================
    @mcp.tool()
    def capture_camera_snapshot(
        device: str = "/dev/video0",
        output_path: str | None = None,
        resolution: str = "1280x720",
        skip_warmup_frames: int = 10,
    ) -> dict[str, Any]:
        """Capture a photo from a connected Webcam or USB Microscope to inspect physical hardware.

        Use this to visually verify if an LED on the board is turned on, read an OLED/LCD display,
        or inspect PCB soldering and jumper wiring on the desk.

        Args:
            device: Video device path on Linux (e.g. '/dev/video0', '/dev/video1').
            output_path: Optional file path to save the captured PNG image.
            resolution: Capture resolution such as '1280x720' or '1920x1080'.
            skip_warmup_frames: Number of initial frames to skip so camera auto-exposure settles (default 10).
        """
        if not os.path.exists(device):
            return {
                "success": False,
                "device": device,
                "error": f"Video device '{device}' does not exist. Call `list_media_devices` to check available `/dev/video*` nodes.",
            }

        if not shutil.which("ffmpeg"):
            return {
                "success": False,
                "error": "`ffmpeg` is required to capture frames from `/dev/video*`.",
            }

        if output_path:
            out_file = Path(output_path).expanduser().resolve()
            out_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp_name = tempfile.mkstemp(prefix="hw_cam_", suffix=".png")
            os.close(fd)
            out_file = Path(tmp_name)

        skip_n = max(0, min(skip_warmup_frames, 60))
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "v4l2",
            "-video_size",
            resolution,
            "-i",
            device,
            "-vf",
            f"select='gte(n,{skip_n})'",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(out_file),
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )
            if proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                return {
                    "success": True,
                    "device": device,
                    "resolution": resolution,
                    "file_path": str(out_file),
                    "file_size_bytes": out_file.stat().st_size,
                }
            return {
                "success": False,
                "device": device,
                "error": proc.stderr[-1500:] if proc.stderr else "Failed to capture frame",
            }
        except Exception as exc:
            return {"success": False, "device": device, "error": str(exc)}

    # =========================================================================
    # 2. Logic Analyzer & Protocol Decoder (sigrok-cli)
    # =========================================================================
    @mcp.tool()
    def sigrok_scan_devices() -> dict[str, Any]:
        """Scan for connected Logic Analyzers, Oscilloscopes, and Multimeters via `sigrok-cli`.

        Supports FX2lafw (24MHz 8-ch Saleae logic clones), DSLogic, Kingst, Rigol, and other sigrok drivers.
        """
        exe = shutil.which("sigrok-cli")
        if not exe:
            return {
                "success": False,
                "installed": False,
                "error": "`sigrok-cli` is not installed on the host machine.",
                "install_hint": "Install with: `sudo apt install sigrok-cli pulseview sigrok-firmware-fx2lafw`",
            }

        proc = subprocess.run(
            [exe, "--scan"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return {
            "success": proc.returncode == 0,
            "installed": True,
            "devices": lines,
            "raw_output": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }

    @mcp.tool()
    def sigrok_capture_and_decode(
        driver: str = "fx2lafw",
        samplerate: str = "1m",
        samples: int | None = 10000,
        time_ms: int | None = None,
        channels: str | None = None,
        protocol_decoder: str | None = None,
        output_file: str | None = None,
    ) -> dict[str, Any]:
        """Capture digital signal pulses from a Logic Analyzer and optionally decode protocols (UART, I2C, SPI, PWM).

        Args:
            driver: Sigrok driver name (default 'fx2lafw' for 8-ch 24MHz logic analyzers, or 'demo' for testing).
            samplerate: Sample rate string (e.g. '1m' for 1MHz, '4m' for 4MHz, '24m' for 24MHz).
            samples: Number of samples to capture (e.g. 10000). Ignored if `time_ms` is set.
            time_ms: Capture duration in milliseconds (e.g. 500 for 500ms). Overrides `samples` if provided.
            channels: Optional channel selection (e.g. 'D0,D1' or 'D0=sda,D1=scl').
            protocol_decoder: Optional sigrok protocol decoder specification
                              (e.g. 'uart:baudrate=115200:rx=D0', 'i2c:scl=D0:sda=D1', 'spi:clk=D0:mosi=D1:miso=D2:cs=D3').
            output_file: Optional file path to save raw capture (.sr format).
        """
        exe = shutil.which("sigrok-cli")
        if not exe:
            return {
                "success": False,
                "error": "`sigrok-cli` is not installed. Run `sudo apt install sigrok-cli sigrok-firmware-fx2lafw`.",
            }

        cmd = [exe, "-d", driver, "--config", f"samplerate={samplerate}"]
        if channels:
            cmd.extend(["-C", channels])
        if time_ms is not None:
            cmd.extend(["--time", f"{time_ms}ms"])
        elif samples is not None:
            cmd.extend(["--samples", str(samples)])

        if protocol_decoder:
            cmd.extend(["-P", protocol_decoder])
        if output_file:
            out_path = str(Path(output_file).expanduser().resolve())
            cmd.extend(["-o", out_path])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False,
            )
            return {
                "success": proc.returncode == 0,
                "command": " ".join(shlex.quote(c) for c in cmd),
                "decoded_or_captured_output": proc.stdout[-15000:] if proc.stdout else "",
                "stderr": proc.stderr[-5000:] if proc.stderr else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # =========================================================================
    # 3. Android / ADB Hardware & SBC Control
    # =========================================================================
    @mcp.tool()
    def adb_list_devices() -> dict[str, Any]:
        """List connected Android phones, tablets, or embedded Android boards via ADB."""
        exe = shutil.which("adb")
        if not exe:
            return {
                "success": False,
                "installed": False,
                "error": "`adb` (Android Debug Bridge) is not installed.",
                "install_hint": "Install with: `sudo apt install adb`",
            }

        proc = subprocess.run(
            [exe, "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
        devices: list[dict[str, str]] = []
        for line in proc.stdout.splitlines()[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(maxsplit=2)
            devices.append(
                {
                    "serial": parts[0] if len(parts) > 0 else "",
                    "state": parts[1] if len(parts) > 1 else "",
                    "details": parts[2] if len(parts) > 2 else "",
                }
            )

        return {
            "success": proc.returncode == 0,
            "installed": True,
            "count": len(devices),
            "devices": devices,
        }

    @mcp.tool()
    def adb_command(
        command: str,
        device_serial: str | None = None,
        is_shell: bool = True,
        timeout_sec: float = 20.0,
    ) -> dict[str, Any]:
        """Execute an ADB shell command or host ADB operation on a connected Android device.

        Args:
            command: Shell command (e.g. 'logcat -d -t 50', 'dumpsys battery', 'input keyevent 26')
                     or ADB subcommand when is_shell=False (e.g. 'install app.apk', 'forward tcp:8000 tcp:8000').
            device_serial: Optional target device serial from `adb_list_devices` (when multiple devices are connected).
            is_shell: If True (default), runs `adb shell <command>`. If False, runs `adb <command>`.
            timeout_sec: Command timeout in seconds (default 20.0).
        """
        exe = shutil.which("adb")
        if not exe:
            return {
                "success": False,
                "error": "`adb` is not installed. Run `sudo apt install adb`.",
            }

        cmd_parts = shlex.split(command)
        if not cmd_parts:
            return {"success": False, "error": "Command cannot be empty."}

        cmd = [exe]
        if device_serial:
            cmd.extend(["-s", device_serial])
        if is_shell:
            cmd.append("shell")
            cmd.extend(cmd_parts)
        else:
            cmd.extend(cmd_parts)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            return {
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "command": " ".join(shlex.quote(c) for c in cmd),
                "stdout": proc.stdout[-15000:] if proc.stdout else "",
                "stderr": proc.stderr[-5000:] if proc.stderr else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
