"""Comprehensive test suite for Hardware Tooling MCP Server across all 8 modules."""

from __future__ import annotations

import asyncio
import json
import math
import os
import pty
import shlex
import struct
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hardware_tooling_mcp.server import mcp
from hardware_tooling_mcp.tools.audio_media import _analyze_wav_signal
from hardware_tooling_mcp.tools.gui_automation import _normalize_xdotool_keys


def test_registered_tools() -> None:
    """Verify that all 29 expected hardware and OS tools are registered on the MCP server."""
    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}

    expected = {
        # 1. Serial Bridge
        "list_serial_ports",
        "read_serial_logs",
        "send_serial_command",
        "toggle_dtr_rts",
        # 2. Toolchains & Diagnostics
        "check_toolchains",
        "check_prerequisites",
        "compile_and_flash",
        "esptool_command",
        "run_custom_toolchain",
        # 3. Process & Port Manager
        "list_processes",
        "find_port_occupiers",
        "free_serial_port",
        "start_process",
        "kill_process",
        # 4. GPIO / I2C / SPI Bridge
        "scan_hardware_bridges",
        "ftdi_gpio_control",
        "ftdi_i2c_scan",
        "ftdi_i2c_transfer",
        "ftdi_spi_transfer",
        # 5. Audio & Media
        "list_media_devices",
        "set_audio_volume",
        "record_audio_sample",
        "play_test_tone",
        # 6. GUI Automation
        "take_screenshot",
        "send_hotkey",
        # 7. Bluetooth Low Energy (BLE)
        "ble_scan_devices",
        "ble_inspect_gatt",
        "ble_read_write_characteristic",
        # 8. External Devices (Camera/Microscope, Logic Analyzer, Android ADB)
        "capture_camera_snapshot",
        "sigrok_scan_devices",
        "sigrok_capture_and_decode",
        "adb_list_devices",
        "adb_command",
    }

    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"
    assert len(tool_names) == 33


def test_call_safe_discovery_tools() -> None:
    """Smoke-test non-destructive discovery tools on the host machine."""
    ports_res = asyncio.run(mcp.call_tool("list_serial_ports", {"include_symlinks": False}))
    assert json.loads(ports_res.content[0].text)["count"] >= 0

    tc_res = asyncio.run(mcp.call_tool("check_toolchains", {}))
    assert "toolchains" in json.loads(tc_res.content[0].text)

    prereq_res = asyncio.run(mcp.call_tool("check_prerequisites", {}))
    prereq_data = json.loads(prereq_res.content[0].text)
    assert "permissions" in prereq_data and "toolchains" in prereq_data

    proc_res = asyncio.run(mcp.call_tool("list_processes", {"filter_name": "python", "limit": 5}))
    assert json.loads(proc_res.content[0].text)["count"] >= 1

    bridge_res = asyncio.run(mcp.call_tool("scan_hardware_bridges", {}))
    assert "linux_i2c_buses" in json.loads(bridge_res.content[0].text)

    media_res = asyncio.run(mcp.call_tool("list_media_devices", {}))
    assert "video_devices" in json.loads(media_res.content[0].text)

    sigrok_res = asyncio.run(mcp.call_tool("sigrok_scan_devices", {}))
    assert "installed" in json.loads(sigrok_res.content[0].text)

    adb_res = asyncio.run(mcp.call_tool("adb_list_devices", {}))
    assert "installed" in json.loads(adb_res.content[0].text)


def test_serial_pty_send_and_crash_detection() -> None:
    """Simulate a real microcontroller over a Linux pseudo-terminal (PTY) to test send_serial_command (text & hex) and read_serial_logs."""
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    def mcu_responder() -> None:
        # 1. Read text command
        data = os.read(master_fd, 64)
        if b"LED_ON" in data:
            os.write(master_fd, b"ACK:LED_ON_OK\r\n")
        # 2. Read hex command (0xAA 0x55)
        data2 = os.read(master_fd, 64)
        if b"\xaa\x55" in data2:
            os.write(master_fd, b"\xaa\x55\x00")
        time.sleep(0.5)
        # 3. Emit simulated ESP32 crash dump for read_serial_logs
        os.write(
            master_fd,
            b"I (1020) main: Starting sensor loop\r\n"
            b"Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.\r\n"
            b"Backtrace: 0x400d1234:0x3ffb5000 0x400d5678:0x3ffb5020\r\n"
            b"Rebooting...\r\n",
        )

    t = threading.Thread(target=mcu_responder, daemon=True)
    t.start()

    try:
        # 1. Test text send_serial_command
        send_res = asyncio.run(
            mcp.call_tool(
                "send_serial_command",
                {
                    "port": slave_name,
                    "data": "LED_ON",
                    "baudrate": 115200,
                    "read_response_sec": 0.3,
                },
            )
        )
        send_payload = json.loads(send_res.content[0].text)
        assert send_payload["success"] is True
        assert "ACK:LED_ON_OK" in send_payload["response_text"]

        # 2. Test hex send_serial_command
        hex_res = asyncio.run(
            mcp.call_tool(
                "send_serial_command",
                {
                    "port": slave_name,
                    "data": "AA 55",
                    "encoding": "hex",
                    "baudrate": 115200,
                    "read_response_sec": 0.3,
                },
            )
        )
        hex_payload = json.loads(hex_res.content[0].text)
        assert hex_payload["success"] is True
        assert "aa 55 00" in hex_payload["response_hex"]

        # 3. Test read_serial_logs with automatic crash dump detection
        log_res = asyncio.run(
            mcp.call_tool(
                "read_serial_logs",
                {
                    "port": slave_name,
                    "baudrate": 115200,
                    "timeout_sec": 1.5,
                    "stop_on_pattern": "Rebooting",
                },
            )
        )
        log_payload = json.loads(log_res.content[0].text)
        assert log_payload["success"] is True
        assert log_payload["crash_detected"] is True
        assert any("Guru Meditation Error" in h for h in log_payload["crash_highlights"])
    finally:
        os.close(master_fd)
        os.close(slave_fd)


def test_process_and_port_lock_management() -> None:
    """Test starting a background process that holds a serial port, detecting it with find_port_occupiers, and freeing it."""
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    try:
        # Start a background process that opens slave_name and sleeps
        start_res = asyncio.run(
            mcp.call_tool(
                "start_process",
                {
                    "command": sys.executable,
                    "args": ["-c", f"import time; f = open({slave_name!r}, 'rb'); time.sleep(30)"],
                    "background": True,
                },
            )
        )
        start_data = json.loads(start_res.content[0].text)
        assert start_data["success"] is True
        bg_pid = start_data["pid"]
        time.sleep(0.3)

        # Verify find_port_occupiers sees bg_pid holding slave_name
        occ_res = asyncio.run(mcp.call_tool("find_port_occupiers", {"port": slave_name}))
        occ_data = json.loads(occ_res.content[0].text)
        assert occ_data["is_busy"] is True
        pids = [p["pid"] for p in occ_data["occupying_processes"]]
        assert bg_pid in pids

        # Kill the background process via kill_process
        kill_res = asyncio.run(mcp.call_tool("kill_process", {"pid": bg_pid, "force": True}))
        kill_data = json.loads(kill_res.content[0].text)
        assert kill_data["success"] is True
    finally:
        os.close(master_fd)
        os.close(slave_fd)


def test_custom_toolchain_and_helpers() -> None:
    """Test run_custom_toolchain, WAV audio signal analysis, and GUI hotkey normalization."""
    # 1. run_custom_toolchain
    tc_res = asyncio.run(
        mcp.call_tool(
            "run_custom_toolchain",
            {"command": f"{shlex.quote(sys.executable)} -c \"print('BUILD_SUCCESS_123')\""},
        )
    )
    tc_data = json.loads(tc_res.content[0].text)
    assert tc_data["success"] is True
    assert "BUILD_SUCCESS_123" in tc_data["stdout"]

    # 2. Audio WAV signal analysis (silent vs active sine wave)
    with tempfile.TemporaryDirectory() as tmpdir:
        silent_wav = Path(tmpdir) / "silent.wav"
        tone_wav = Path(tmpdir) / "tone.wav"
        sample_rate = 16000

        with wave.open(str(silent_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * sample_rate)

        silent_stats = _analyze_wav_signal(silent_wav)
        assert silent_stats["is_silent"] is True

        with wave.open(str(tone_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            samples = [int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(sample_rate)]
            wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

        tone_stats = _analyze_wav_signal(tone_wav)
        assert tone_stats["is_silent"] is False
        assert tone_stats["peak_dbfs"] > -10.0

    # 3. GUI hotkey normalization
    assert _normalize_xdotool_keys("Ctrl + Shift + B") == "ctrl+shift+b"
    assert _normalize_xdotool_keys("Alt + Enter") == "alt+Return"


def test_stdio_mcp_transport() -> None:
    """Verify full MCP client-server communication over stdio subprocess."""

    async def _run() -> None:
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "hardware_tooling_mcp.server"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.server_info.name == "Hardware Tooling"
                tools = await session.list_tools()
                assert len(tools.tools) == 33

    asyncio.run(_run())
