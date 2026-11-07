"""GUI & Application Automation tools (Screenshots, Hotkeys, Window Management)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer


def _normalize_xdotool_keys(keys: str) -> str:
    """Convert common hotkey notation like 'Ctrl + Shift + B' to xdotool format 'ctrl+shift+b'."""
    parts = [p.strip() for p in keys.replace("-", "+").split("+") if p.strip()]
    mapped: list[str] = []
    key_map = {
        "ctrl": "ctrl",
        "control": "ctrl",
        "shift": "shift",
        "alt": "alt",
        "super": "super",
        "win": "super",
        "cmd": "super",
        "enter": "Return",
        "return": "Return",
        "esc": "Escape",
        "escape": "Escape",
        "space": "space",
        "tab": "Tab",
        "backspace": "BackSpace",
        "delete": "Delete",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
    }
    for part in parts:
        lower = part.lower()
        if lower in key_map:
            mapped.append(key_map[lower])
        elif len(part) == 1:
            mapped.append(part.lower())
        else:
            mapped.append(part)
    return "+".join(mapped)


def register_gui_automation_tools(mcp: MCPServer) -> None:
    """Register GUI & Screen Automation tools on the MCPServer instance."""

    @mcp.tool()
    def take_screenshot(
        output_path: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Capture a screenshot of the full screen or a specific region (`x,y,width,height`).

        Useful for letting the AI inspect application windows, error dialogs, or logic analyzer/oscilloscope GUIs.

        Args:
            output_path: Optional file path to save the PNG image (defaults to a temporary file).
            region: Optional region in format 'x,y,width,height' (e.g., '0,0,800,600').
        """
        if output_path:
            out_file = Path(output_path).expanduser().resolve()
            out_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp_name = tempfile.mkstemp(prefix="hw_screenshot_", suffix=".png")
            os.close(fd)
            out_file = Path(tmp_name)

        display = os.environ.get("DISPLAY", ":0")

        # If region is requested and ffmpeg is available, use x11grab for exact region cropping
        if region and shutil.which("ffmpeg"):
            try:
                parts = [int(p.strip()) for p in region.split(",")]
                if len(parts) != 4:
                    return {
                        "success": False,
                        "error": "Region must be formatted as 'x,y,width,height' (e.g. '100,100,800,600').",
                    }
                x, y, w, h = parts
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "x11grab",
                    "-video_size",
                    f"{w}x{h}",
                    "-i",
                    f"{display}+{x},{y}",
                    "-frames:v",
                    "1",
                    str(out_file),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0, check=False)
                if proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                    return {
                        "success": True,
                        "backend": "ffmpeg-x11grab",
                        "region": region,
                        "file_path": str(out_file),
                        "file_size_bytes": out_file.stat().st_size,
                    }
            except Exception as exc:
                return {"success": False, "error": f"Failed to parse or capture region: {exc}"}

        # Fullscreen fallback #1: gnome-screenshot
        if shutil.which("gnome-screenshot"):
            proc = subprocess.run(
                ["gnome-screenshot", "-f", str(out_file)],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            if proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                return {
                    "success": True,
                    "backend": "gnome-screenshot",
                    "file_path": str(out_file),
                    "file_size_bytes": out_file.stat().st_size,
                }

        # Fullscreen fallback #2: ffmpeg x11grab
        if shutil.which("ffmpeg"):
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "x11grab",
                    "-i",
                    display,
                    "-frames:v",
                    "1",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            if proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                return {
                    "success": True,
                    "backend": "ffmpeg-x11grab",
                    "file_path": str(out_file),
                    "file_size_bytes": out_file.stat().st_size,
                }

        return {
            "success": False,
            "error": "Could not capture screenshot. Verify DISPLAY environment or install gnome-screenshot/ffmpeg.",
        }

    @mcp.tool()
    def send_hotkey(
        keys: str,
        window_title: str | None = None,
        delay_ms: int = 50,
    ) -> dict[str, Any]:
        """Send keyboard shortcuts or keystrokes to the active window or a specific application window.

        Args:
            keys: Key combination such as 'ctrl+shift+b', 'ctrl+s', 'alt+F4', or 'Return'.
            window_title: Optional window title substring to focus before sending the hotkey.
            delay_ms: Delay between key events in milliseconds (default 50).
        """
        if not shutil.which("xdotool"):
            return {
                "success": False,
                "error": "`xdotool` is not installed. Install with `sudo apt install xdotool`.",
            }

        normalized = _normalize_xdotool_keys(keys)
        try:
            if window_title:
                search_proc = subprocess.run(
                    ["xdotool", "search", "--name", window_title],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )
                win_ids = [w.strip() for w in search_proc.stdout.splitlines() if w.strip()]
                if not win_ids:
                    return {
                        "success": False,
                        "error": f"No window found matching title '{window_title}'.",
                    }
                target_win = win_ids[-1]
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", target_win],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )

            proc = subprocess.run(
                ["xdotool", "key", "--delay", str(delay_ms), normalized],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            return {
                "success": proc.returncode == 0,
                "keys_sent": normalized,
                "window_title": window_title,
                "stderr": proc.stderr.strip() if proc.stderr else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
