"""USB / Serial Bridge tools for microcontroller communication and debugging."""

from __future__ import annotations

import re
import time
from typing import Any

import serial
import serial.tools.list_ports
from mcp.server.mcpserver import MCPServer

# Known USB VID:PID hints for common embedded boards and USB-UART chips
KNOWN_USB_CHIPS: dict[tuple[int, int], str] = {
    (0x10C4, 0xEA60): "Silicon Labs CP210x (Common on ESP32 / NodeMCU)",
    (0x1A86, 0x7523): "QinHeng CH340/CH341 (Common on Arduino / ESP8266 / ESP32)",
    (0x1A86, 0x55D4): "QinHeng CH9102 (Common on ESP32 / Wemos)",
    (0x0403, 0x6001): "FTDI FT232R USB UART",
    (0x0403, 0x6014): "FTDI FT232H Single HS USB-UART/FIFO IC (GPIO/I2C/SPI capable)",
    (0x303A, 0x1001): "Espressif ESP32-S2/S3/C3/C6 Native USB Serial/JTAG",
    (0x303A, 0x0002): "Espressif ESP32-S2 Native USB CDC",
    (0x2341, 0x0043): "Arduino Uno R3",
    (0x2341, 0x0001): "Arduino Uno",
    (0x2E8A, 0x000A): "Raspberry Pi Pico (RP2040 CDC UART)",
    (0x2E8A, 0x0005): "Raspberry Pi Pico MicroPython CDC",
    (0x0483, 0x5740): "STMicroelectronics STM32 Virtual COM Port",
}

CRASH_SIGNATURES = [
    r"Guru Meditation Error",
    r"Backtrace:\s*0x[0-9a-fA-F]+",
    r"Brownout detector was triggered",
    r"rst:0x[0-9a-fA-F]+",
    r"assert failed:",
    r"HardFault_Handler",
    r"panic\s*:",
    r"Stack overflow",
]


def _identify_board_hint(vid: int | None, pid: int | None, description: str, manufacturer: str) -> str:
    if vid is not None and pid is not None and (vid, pid) in KNOWN_USB_CHIPS:
        return KNOWN_USB_CHIPS[(vid, pid)]
    combined = f"{description} {manufacturer}".lower()
    if "cp210" in combined:
        return "Silicon Labs CP210x USB-to-UART (Likely ESP32/DevKit)"
    if "ch340" in combined or "ch341" in combined or "ch9102" in combined:
        return "WCH CH34x/CH9102 USB-to-UART (Likely ESP32/Arduino)"
    if "esp32" in combined or "espressif" in combined:
        return "Espressif ESP32 series board"
    if "arduino" in combined:
        return "Arduino board"
    if "pico" in combined or "rp2040" in combined or "rp2350" in combined:
        return "Raspberry Pi Pico (RP2040/RP2350)"
    if "ftdi" in combined or "ft232" in combined:
        return "FTDI USB Interface"
    if "stlink" in combined or "stm32" in combined:
        return "STM32 / ST-Link Interface"
    return "Generic Serial / UART Device"


def register_serial_tools(mcp: MCPServer) -> None:
    """Register USB and Serial communication tools on the FastMCP instance."""

    @mcp.tool()
    def list_serial_ports(
        include_symlinks: bool = False,
        hide_phantom_ttys: bool = True,
    ) -> dict[str, Any]:
        """Scan and list all USB/Serial ports connected to the computer.

        Identifies VID/PID, manufacturer, serial number, and provides hints about
        what board or USB-to-UART chip is connected (e.g. ESP32, Arduino, Pico, FTDI).

        Args:
            include_symlinks: Include symlinked device paths.
            hide_phantom_ttys: Filter out unpopulated Linux /dev/ttyS* ports with 'n/a' hwid (default True).
        """
        ports = serial.tools.list_ports.comports(include_links=include_symlinks)
        result_list: list[dict[str, Any]] = []

        for p in sorted(ports, key=lambda x: x.device):
            if hide_phantom_ttys and (p.hwid or "n/a") == "n/a" and (p.description or "n/a") == "n/a":
                continue
            vid_hex = f"0x{p.vid:04X}" if p.vid is not None else None
            pid_hex = f"0x{p.pid:04X}" if p.pid is not None else None
            hint = _identify_board_hint(
                p.vid, p.pid, p.description or "", p.manufacturer or ""
            )
            result_list.append(
                {
                    "port": p.device,
                    "name": p.name,
                    "description": p.description,
                    "hwid": p.hwid,
                    "vid": vid_hex,
                    "pid": pid_hex,
                    "serial_number": p.serial_number,
                    "location": p.location,
                    "manufacturer": p.manufacturer,
                    "product": p.product,
                    "interface": p.interface,
                    "board_hint": hint,
                }
            )

        return {
            "count": len(result_list),
            "ports": result_list,
        }

    @mcp.tool()
    def read_serial_logs(
        port: str,
        baudrate: int = 115200,
        timeout_sec: float = 5.0,
        max_lines: int = 500,
        stop_on_pattern: str | None = None,
        stop_on_crash_dump: bool = True,
        reset_before_read: bool = False,
    ) -> dict[str, Any]:
        """Open a serial port and read stdout/logs for `timeout_sec` seconds.

        Automatically detects MCU crash dumps (e.g., ESP32 Guru Meditation Error,
        Brownout detector, Backtrace, HardFault) and extracts them for debugging.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0', '/dev/ttyACM0', 'COM3').
            baudrate: Baud rate (default 115200).
            timeout_sec: Maximum duration in seconds to listen (default 5.0, max 60.0).
            max_lines: Maximum number of lines to collect before stopping.
            stop_on_pattern: Optional regex or substring to stop reading early when matched.
            stop_on_crash_dump: Whether to finish reading shortly after detecting a crash dump.
            reset_before_read: Pulse DTR/RTS to reset the board right after opening the port.
        """
        timeout_sec = max(0.2, min(timeout_sec, 60.0))
        lines: list[str] = []
        detected_crashes: list[str] = []
        matched_pattern = False
        crash_post_lines_remaining: int | None = None

        try:
            with serial.Serial(port=port, baudrate=baudrate, timeout=0.1) as ser:
                if reset_before_read:
                    ser.dtr = False
                    ser.rts = True
                    time.sleep(0.1)
                    ser.rts = False
                    ser.reset_input_buffer()

                start_time = time.monotonic()
                while (time.monotonic() - start_time) < timeout_sec and len(lines) < max_lines:
                    raw = ser.readline()
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    lines.append(line)

                    # Check crash signatures
                    for sig in CRASH_SIGNATURES:
                        if re.search(sig, line, re.IGNORECASE):
                            detected_crashes.append(line)
                            if stop_on_crash_dump and crash_post_lines_remaining is None:
                                # Capture up to 25 more lines after crash header to get full stacktrace
                                crash_post_lines_remaining = 25

                    if stop_on_pattern:
                        try:
                            is_match = bool(re.search(stop_on_pattern, line))
                        except re.error:
                            is_match = stop_on_pattern in line
                        if is_match:
                            matched_pattern = True
                            break

                    if crash_post_lines_remaining is not None:
                        crash_post_lines_remaining -= 1
                        if crash_post_lines_remaining <= 0:
                            break

                elapsed = round(time.monotonic() - start_time, 3)

            return {
                "success": True,
                "port": port,
                "baudrate": baudrate,
                "elapsed_sec": elapsed,
                "line_count": len(lines),
                "matched_pattern": matched_pattern,
                "crash_detected": len(detected_crashes) > 0,
                "crash_highlights": detected_crashes,
                "logs": "\n".join(lines),
            }
        except serial.SerialException as exc:
            return {
                "success": False,
                "port": port,
                "error": str(exc),
                "hint": "Use `find_port_occupiers` or `list_serial_ports` to verify if the port exists or is locked by another process.",
            }

    @mcp.tool()
    def send_serial_command(
        port: str,
        data: str,
        baudrate: int = 115200,
        encoding: str = "utf-8",
        line_ending: str = "\n",
        read_response_sec: float = 1.5,
    ) -> dict[str, Any]:
        """Send a command string or raw hex bytes to a serial port and optionally read the response.

        Args:
            port: Serial port device (e.g., '/dev/ttyUSB0').
            data: Text string to send, or hex bytes string (e.g., 'AA 55 01 FF') when encoding='hex'.
            baudrate: Serial baud rate (default 115200).
            encoding: 'utf-8', 'ascii', or 'hex' for raw byte arrays.
            line_ending: Appended to text payloads ('\\n', '\\r\\n', '\\r', or '' for none). Ignored if encoding='hex'.
            read_response_sec: Seconds to listen for response after sending (0 to skip reading).
        """
        try:
            if encoding.lower() == "hex":
                cleaned = re.sub(r"[^0-9a-fA-F]", "", data)
                if len(cleaned) % 2 != 0:
                    return {
                        "success": False,
                        "error": "Hex string must have an even number of hex digits.",
                    }
                payload = bytes.fromhex(cleaned)
            else:
                payload = (data + line_ending).encode(encoding)

            response_lines: list[str] = []
            response_hex: str = ""

            with serial.Serial(port=port, baudrate=baudrate, timeout=0.1) as ser:
                # Hold DTR/RTS steady to avoid unintentional board reset on open if possible
                bytes_written = ser.write(payload)
                ser.flush()

                if read_response_sec > 0:
                    read_response_sec = min(read_response_sec, 30.0)
                    raw_chunks = bytearray()
                    start = time.monotonic()
                    while (time.monotonic() - start) < read_response_sec:
                        chunk = ser.read(ser.in_waiting or 1)
                        if chunk:
                            raw_chunks.extend(chunk)
                    if raw_chunks:
                        response_hex = raw_chunks.hex(" ")
                        response_lines = (
                            raw_chunks.decode("utf-8", errors="replace").splitlines()
                        )

            return {
                "success": True,
                "port": port,
                "baudrate": baudrate,
                "bytes_written": bytes_written,
                "payload_hex": payload.hex(" "),
                "response_text": "\n".join(response_lines),
                "response_hex": response_hex,
            }
        except (serial.SerialException, LookupError, ValueError) as exc:
            return {
                "success": False,
                "port": port,
                "error": str(exc),
            }

    @mcp.tool()
    def toggle_dtr_rts(
        port: str,
        mode: str = "reset",
        dtr: bool | None = None,
        rts: bool | None = None,
        pulse_ms: int = 100,
    ) -> dict[str, Any]:
        """Control DTR and RTS lines on a serial port to reset the board or enter bootloader mode.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0').
            mode:
                - 'reset': Pulse RTS/DTR to hard-reset the microcontroller.
                - 'esp32_bootloader': Classic ESP32 auto-program DTR/RTS sequence to enter ROM download mode.
                - 'custom': Explicitly set DTR and RTS to the boolean values passed in `dtr` and `rts`.
            dtr: Explicit DTR state when mode='custom'.
            rts: Explicit RTS state when mode='custom'.
            pulse_ms: Duration in milliseconds for reset/bootloader pulses (default 100ms).
        """
        pulse_sec = max(0.01, min(pulse_ms / 1000.0, 5.0))
        try:
            with serial.Serial(port=port, baudrate=115200, timeout=0.1) as ser:
                if mode == "reset":
                    ser.dtr = False
                    ser.rts = True
                    time.sleep(pulse_sec)
                    ser.rts = False
                    action_desc = f"Pulsed RTS for {pulse_ms}ms to reset board"
                elif mode == "esp32_bootloader":
                    # Standard esptool classic_reset sequence (IO0=DTR, EN=RTS via dual transistor circuit)
                    ser.dtr = False
                    ser.rts = True
                    time.sleep(pulse_sec)
                    ser.dtr = True
                    ser.rts = False
                    time.sleep(max(0.05, pulse_sec))
                    ser.dtr = False
                    action_desc = "Executed ESP32 DTR/RTS bootloader entry sequence"
                elif mode == "custom":
                    if dtr is not None:
                        ser.dtr = dtr
                    if rts is not None:
                        ser.rts = rts
                    time.sleep(pulse_sec)
                    action_desc = f"Set custom DTR={dtr}, RTS={rts} for {pulse_ms}ms"
                else:
                    return {
                        "success": False,
                        "error": f"Unknown mode '{mode}'. Choose 'reset', 'esp32_bootloader', or 'custom'.",
                    }

            return {
                "success": True,
                "port": port,
                "mode": mode,
                "action": action_desc,
            }
        except (serial.SerialException, LookupError, ValueError) as exc:
            return {
                "success": False,
                "port": port,
                "error": str(exc),
            }
