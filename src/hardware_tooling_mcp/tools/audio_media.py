"""Audio & Media Device Control tools (Microphone recording, signal analysis, speaker volume, test tones, webcams)."""

from __future__ import annotations

import glob
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer


def _analyze_wav_signal(wav_path: Path) -> dict[str, Any]:
    """Compute RMS, peak level, dBFS, and silence check for a 16-bit PCM WAV file."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        if sampwidth != 2 or n_frames == 0:
            return {
                "channels": n_channels,
                "sample_rate": framerate,
                "frames": n_frames,
            }

        total_samples = len(raw) // 2
        samples = struct.unpack(f"<{total_samples}h", raw)
        peak = max((abs(s) for s in samples), default=0)
        sum_sq = sum(float(s) * float(s) for s in samples)
        rms = math.sqrt(sum_sq / total_samples) if total_samples > 0 else 0.0

        rms_dbfs = round(20.0 * math.log10(rms / 32768.0), 2) if rms > 0 else -100.0
        peak_dbfs = round(20.0 * math.log10(peak / 32768.0), 2) if peak > 0 else -100.0

        return {
            "channels": n_channels,
            "sample_rate": framerate,
            "duration_sec": round(n_frames / framerate, 2) if framerate else 0.0,
            "rms_amplitude": round(rms, 1),
            "peak_amplitude": peak,
            "rms_dbfs": rms_dbfs,
            "peak_dbfs": peak_dbfs,
            "is_silent": rms_dbfs < -55.0,
            "status_hint": (
                "SILENT / NO SIGNAL detected (check mic mute, wiring, or gain)"
                if rms_dbfs < -55.0
                else "ACTIVE AUDIO SIGNAL detected"
            ),
        }
    except Exception as exc:
        return {"analysis_error": str(exc)}


def register_audio_media_tools(mcp: MCPServer) -> None:
    """Register Audio, Microphone, Speaker, and Webcam hardware control tools."""

    @mcp.tool()
    def list_media_devices() -> dict[str, Any]:
        """List connected audio input/output devices (microphones, speakers) and video/webcam devices."""
        result: dict[str, Any] = {
            "video_devices": sorted(glob.glob("/dev/video*")),
            "alsa_capture_devices": "",
            "alsa_playback_devices": "",
            "pipewire_pulse_status": "",
        }

        if shutil.which("arecord"):
            proc = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5.0, check=False)
            result["alsa_capture_devices"] = proc.stdout.strip()

        if shutil.which("aplay"):
            proc = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5.0, check=False)
            result["alsa_playback_devices"] = proc.stdout.strip()

        if shutil.which("wpctl"):
            proc = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=5.0, check=False)
            result["pipewire_pulse_status"] = proc.stdout.strip()
        elif shutil.which("pactl"):
            sinks = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5.0, check=False)
            sources = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=5.0, check=False)
            result["pipewire_pulse_status"] = f"Sinks:\n{sinks.stdout}\nSources:\n{sources.stdout}"

        return result

    @mcp.tool()
    def set_audio_volume(
        target: str = "sink",
        volume_percent: int | None = None,
        mute: bool | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Set volume or mute state for speaker ('sink') or microphone ('source').

        Args:
            target: 'sink' (speaker/output) or 'source' (microphone/input).
            volume_percent: Volume level from 0 to 150 (e.g., 80 for 80%).
            mute: True to mute, False to unmute, or None to leave unchanged.
            device_id: Optional PipeWire/PulseAudio node ID or name (defaults to default sink/source).
        """
        if target not in ("sink", "source"):
            return {"success": False, "error": "Invalid target. Must be 'sink' (speaker) or 'source' (microphone)."}

        actions: list[str] = []
        if shutil.which("wpctl"):
            default_node = "@DEFAULT_AUDIO_SINK@" if target == "sink" else "@DEFAULT_AUDIO_SOURCE@"
            node = device_id or default_node
            if volume_percent is not None:
                vol_clamped = max(0, min(volume_percent, 150))
                subprocess.run(
                    ["wpctl", "set-volume", node, f"{vol_clamped}%"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                actions.append(f"Set {node} volume to {vol_clamped}%")
            if mute is not None:
                subprocess.run(
                    ["wpctl", "set-mute", node, "1" if mute else "0"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                actions.append(f"Set {node} mute={mute}")
            status = subprocess.run(
                ["wpctl", "get-volume", node], capture_output=True, text=True, check=False
            )
            return {
                "success": True,
                "backend": "wpctl",
                "node": node,
                "actions": actions,
                "current_state": status.stdout.strip(),
            }

        elif shutil.which("pactl"):
            default_node = "@DEFAULT_SINK@" if target == "sink" else "@DEFAULT_SOURCE@"
            node = device_id or default_node
            vol_cmd = "set-sink-volume" if target == "sink" else "set-source-volume"
            mute_cmd = "set-sink-mute" if target == "sink" else "set-source-mute"
            if volume_percent is not None:
                vol_clamped = max(0, min(volume_percent, 150))
                subprocess.run(
                    ["pactl", vol_cmd, node, f"{vol_clamped}%"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                actions.append(f"Set {node} volume to {vol_clamped}%")
            if mute is not None:
                subprocess.run(
                    ["pactl", mute_cmd, node, "1" if mute else "0"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                actions.append(f"Set {node} mute={mute}")
            return {
                "success": True,
                "backend": "pactl",
                "node": node,
                "actions": actions,
            }

        return {
            "success": False,
            "error": "Neither `wpctl` nor `pactl` was found on the host system.",
        }

    @mcp.tool()
    def record_audio_sample(
        duration_sec: float = 5.0,
        output_path: str | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        alsa_device: str | None = None,
    ) -> dict[str, Any]:
        """Record audio from a microphone for `duration_sec` seconds and analyze the signal level (RMS/dBFS).

        Great for verifying hardware audio output (speaker -> host mic) or testing a connected USB microphone.

        Args:
            duration_sec: Recording duration in seconds (1 to 30, default 5.0).
            output_path: File path to save the .wav file (defaults to a temporary file).
            sample_rate: Sample rate in Hz (default 16000).
            channels: Number of channels (1 for mono, 2 for stereo).
            alsa_device: Optional ALSA device string (e.g. 'default', 'hw:0,0', 'plughw:1,0').
        """
        duration_int = max(1, min(int(round(duration_sec)), 30))
        if output_path:
            out_file = Path(output_path).expanduser().resolve()
            out_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp_name = tempfile.mkstemp(prefix="hw_mic_test_", suffix=".wav")
            os.close(fd)
            out_file = Path(tmp_name)

        if shutil.which("arecord"):
            cmd = [
                "arecord",
                "-f",
                "S16_LE",
                "-r",
                str(sample_rate),
                "-c",
                str(channels),
                "-d",
                str(duration_int),
            ]
            if alsa_device:
                cmd.extend(["-D", alsa_device])
            cmd.append(str(out_file))
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=duration_int + 10,
                check=False,
            )
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": proc.stderr.strip() or proc.stdout.strip(),
                    "command": " ".join(cmd),
                }
        elif shutil.which("ffmpeg"):
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "pulse",
                "-i",
                alsa_device or "default",
                "-t",
                str(duration_int),
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-c:a",
                "pcm_s16le",
                str(out_file),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=duration_int + 10,
                check=False,
            )
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": proc.stderr[-2000:],
                    "command": " ".join(cmd),
                }
        else:
            return {
                "success": False,
                "error": "Neither `arecord` nor `ffmpeg` is available to record audio.",
            }

        signal_stats = _analyze_wav_signal(out_file)
        return {
            "success": True,
            "file_path": str(out_file),
            "file_size_bytes": out_file.stat().st_size if out_file.exists() else 0,
            "signal_analysis": signal_stats,
        }

    @mcp.tool()
    def play_test_tone(
        frequency_hz: int = 440,
        duration_sec: float = 2.0,
    ) -> dict[str, Any]:
        """Play a pure sine wave test tone on the host speakers (useful for testing I2S/ADC mic sensors on an MCU).

        Args:
            frequency_hz: Tone frequency in Hz (default 440Hz A4).
            duration_sec: Duration in seconds (0.5 to 10.0, default 2.0).
        """
        duration_sec = max(0.2, min(duration_sec, 10.0))
        if not shutil.which("ffmpeg"):
            return {"success": False, "error": "`ffmpeg` is required to generate test tones."}

        fd, tmp_wav = tempfile.mkstemp(prefix="hw_tone_", suffix=".wav")
        os.close(fd)
        try:
            gen = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={frequency_hz}:duration={duration_sec}",
                    "-ar",
                    "44100",
                    "-c:a",
                    "pcm_s16le",
                    tmp_wav,
                ],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            if gen.returncode != 0:
                return {"success": False, "error": gen.stderr[-1000:]}

            play_cmd = ["aplay", tmp_wav] if shutil.which("aplay") else ["ffplay", "-nodisp", "-autoexit", tmp_wav]
            play = subprocess.run(play_cmd, capture_output=True, text=True, timeout=duration_sec + 5, check=False)
            return {
                "success": play.returncode == 0,
                "frequency_hz": frequency_hz,
                "duration_sec": duration_sec,
                "player": play_cmd[0],
            }
        finally:
            Path(tmp_wav).unlink(missing_ok=True)
