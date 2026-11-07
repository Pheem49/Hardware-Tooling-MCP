# Hardware-Tooling-MCP

**Embedded & Hardware Tooling Bridge (`hardware-tooling-mcp`)** is a Model Context Protocol (MCP) server that gives AI Agents (Claude Desktop, Cursor, Cline, Roo Code, Antigravity, etc.) direct hands-on access to **physical hardware connected to your computer** and **host OS processes/media** over local `stdio`.

Normally, AI coding assistants live solely in text and source files—they cannot see which USB port an ESP32 is plugged into, read serial panic stack traces, toggle GPIO pins, inspect a board via a USB microscope, or unlock a busy serial port. **Hardware-Tooling-MCP** bridges that gap.

```text
[ Developer (Natural Language) ]
       │
       ▼
[ AI Agent (Claude / Cursor / CLI) ]
       │ (MCP Tool Calls over Local stdio)
       ▼
[ Hardware Tooling MCP Bridge ]
       ├── 1. USB / Serial Bridge (pyserial, DTR/RTS Bootloader & Reset, Crash Dump Detector)
       ├── 2. Firmware Flashing & Toolchains (check_prerequisites, arduino-cli, pio, idf.py, esptool)
       ├── 3. Direct GPIO / I2C / SPI (FT232H / FTDI MPSSE & Linux i2c/spidev/gpiochip)
       ├── 4. Host Process & Port Lock Manager (psutil, lsof, free locked serial ports)
       ├── 5. Audio & Media Control (Mic recording + RMS/dBFS signal analysis, volume, test tones)
       ├── 6. GUI & Screen Automation (take_screenshot, send_hotkey via xdotool/ffmpeg)
       ├── 7. Bluetooth Low Energy (BLE) (bleak: scan, GATT service discovery, characteristic R/W)
       └── 8. Webcam/Microscope Vision, Logic Analyzer (sigrok-cli) & Android ADB
```

---

## Quick Start (Installation & Client Config)

Because this MCP server interacts directly with local USB/Serial ports, Bluetooth, cameras, and OS processes, it runs locally on your machine via `stdio`.

### Option 1: Run directly from GitHub via `uvx` (Recommended — Zero manual setup)

Add the following to your MCP client configuration file:

```json
{
  "mcpServers": {
    "hardware-tooling": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Pheem49/Hardware-Tooling-MCP.git",
        "hardware-tooling-mcp"
      ]
    }
  }
}
```

### Option 2: Run via `uvx` from PyPI

```json
{
  "mcpServers": {
    "hardware-tooling": {
      "command": "uvx",
      "args": ["hardware-tooling-mcp"]
    }
  }
}
```

### Option 3: Local Clone & Development

```bash
git clone https://github.com/Pheem49/Hardware-Tooling-MCP.git
cd Hardware-Tooling-MCP
uv sync
```

Configure your MCP client to point to your local directory:

```json
{
  "mcpServers": {
    "hardware-tooling": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/Hardware-Tooling-MCP",
        "hardware-tooling-mcp"
      ]
    }
  }
}
```

---

## Where to Put Your MCP Config

| AI Client | Configuration File Path |
| :--- | :--- |
| **Claude Desktop (Linux)** | `~/.config/Claude/claude_desktop_config.json` |
| **Claude Desktop (macOS)** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Claude Desktop (Windows)** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Cursor** | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) |
| **Cline / Roo Code (VS Code)** | Open MCP Servers panel in the extension → **Edit MCP Settings** |

---

## Available Tools (33 Tools across 8 Modules)

### 1. USB / Serial Bridge (`tools/serial_bridge.py`)
- `list_serial_ports(include_symlinks, hide_phantom_ttys)` — Scan all connected USB/Serial ports with VID/PID, manufacturer, and automatic board identification (ESP32, Arduino, Raspberry Pi Pico, STM32, CP210x, CH340, FTDI).
- `read_serial_logs(port, baudrate, timeout_sec, max_lines, stop_on_pattern, stop_on_crash_dump, reset_before_read)` — Read serial monitor output with automatic MCU crash dump detection (`Guru Meditation Error`, `Backtrace:`, `Brownout detector`, `HardFault`).
- `send_serial_command(port, data, baudrate, encoding, line_ending, read_response_sec)` — Send text (`utf-8`/`ascii`) or raw byte payloads (`hex`, e.g. `"AA 55 01 FF"`) over UART RX/TX and read back the response. Supports AT commands, G-code, and Modbus RTU frames.
- `toggle_dtr_rts(port, mode, dtr, rts, pulse_ms)` — Hardware-reset the microcontroller (`mode="reset"`) or force ESP32 into ROM bootloader mode (`mode="esp32_bootloader"`) via DTR/RTS lines without pressing physical buttons.

### 2. Firmware Flashing, Toolchains & Readiness (`tools/toolchains.py`)
- `check_prerequisites()` — **Full host environment diagnostic**: verifies Linux serial group permissions (`dialout`/`uucp`), checks installed embedded toolchains, and provides exact installation or permission-fix commands.
- `check_toolchains()` — Detect versions and paths of `arduino-cli`, `pio` (PlatformIO), `idf.py` (ESP-IDF), `esptool`, `openocd`, `avrdude`, `dfu-util`, and `picotool`.
- `compile_and_flash(project_path, toolchain, port, board_fqbn_or_env, action, extra_args, timeout_sec)` — Compile and/or upload firmware using `arduino-cli`, `platformio`, or `esp-idf` (supports `toolchain="auto"` to auto-detect from `platformio.ini`, `CMakeLists.txt`, or `.ino` sketches).
- `esptool_command(operation, port, baudrate, chip, flash_offset, binary_path, extra_args)` — Run `esptool` directly for `chip_id`, `flash_id`, `read_mac`, `erase_flash`, or `write_flash`.
- `run_custom_toolchain(command, working_directory, timeout_sec)` — Execute custom build/flash CLI commands (e.g., `make flash`, `west build`, `cargo embed`, `openocd`).

### 3. Direct GPIO / I2C / SPI Bridge (`tools/gpio_bus.py`)
- `scan_hardware_bridges()` — Discover USB-to-GPIO/I2C/SPI bridges (FTDI `FT232H`, `FT2232H`) and native Linux `/dev/i2c-*`, `/dev/spidev*`, and `/dev/gpiochip*` nodes.
- `ftdi_gpio_control(ftdi_url, direction_mask, write_value)` — Drive or read 8-bit GPIO pins directly via an FTDI USB bridge.
- `ftdi_i2c_scan(ftdi_url, frequency_hz)` — Scan an I2C bus for active 7-bit slave addresses.
- `ftdi_i2c_transfer(address, ftdi_url, register_addr, write_hex, read_length, frequency_hz)` — Read/write I2C registers directly on sensors (e.g. BME280, MPU6050, SSD1306) without needing a microcontroller in between.
- `ftdi_spi_transfer(write_hex, read_length, ftdi_url, cs, freq_hz, mode)` — Perform full-duplex SPI transfers (e.g., reading JEDEC IDs or dumping SPI Flash chips).

### 4. Host Process & Serial Port Lock Management (`tools/process_manager.py`)
- `list_processes(filter_name, limit)` — List running OS processes filtered by name or command line.
- `find_port_occupiers(port)` — Identify which process is holding a lock on a serial port (e.g., `/dev/ttyUSB0`) when you hit `Port busy` errors.
- `free_serial_port(port, force)` — Automatically terminate processes locking a serial port so firmware flashing or monitoring can proceed.
- `start_process(command, args, cwd, background, timeout_sec)` — Launch a foreground or background process on the host OS.
- `kill_process(pid, process_name, force)` — Terminate a process by PID or name.

### 5. Audio & Media Device Control (`tools/audio_media.py`)
- `list_media_devices()` — List microphones, speakers (ALSA / PipeWire / PulseAudio), and video/webcam devices (`/dev/video*`).
- `set_audio_volume(target, volume_percent, mute, device_id)` — Adjust volume or mute/unmute speakers (`sink`) and microphones (`source`).
- `record_audio_sample(duration_sec, output_path, sample_rate, channels, alsa_device)` — Record audio from a microphone and compute signal metrics (`rms_dbfs`, `peak_dbfs`, `is_silent`) to verify whether an audio circuit/amp is actually producing sound.
- `play_test_tone(frequency_hz, duration_sec)` — Generate and play a pure sine wave tone on the host speakers to test microphone sensors (e.g. I2S INMP441) on a board.

### 6. GUI & Screen Automation (`tools/gui_automation.py`)
- `take_screenshot(output_path, region)` — Capture a full-screen or region (`x,y,width,height`) screenshot so the AI can inspect application windows or error dialogs.
- `send_hotkey(keys, window_title, delay_ms)` — Send keyboard shortcuts (e.g., `ctrl+shift+b`, `ctrl+s`) to the active or specified window via `xdotool`.

### 7. Bluetooth Low Energy (BLE) (`tools/ble_bridge.py`)
- `ble_scan_devices(timeout_sec, name_filter)` — Scan for nearby BLE peripherals (ESP32 BLE, nRF52, wireless sensors) with RSSI, service UUIDs, and manufacturer data.
- `ble_inspect_gatt(address, timeout_sec)` — Connect to a BLE device and enumerate all GATT Services, Characteristics, and properties (`read`, `write`, `notify`).
- `ble_read_write_characteristic(address, characteristic_uuid, write_data, encoding, read_after_write, with_response, timeout_sec)` — Read or write text/hex payloads to a BLE GATT Characteristic.

### 8. Webcam/Microscope Vision, Logic Analyzer & Android ADB (`tools/external_devices.py`)
- `capture_camera_snapshot(device, output_path, resolution, skip_warmup_frames)` — Capture a photo from a connected Webcam or USB Microscope (`/dev/video*`) to visually verify LED states, OLED/LCD screens, or PCB wiring.
- `sigrok_scan_devices()` — Discover connected Logic Analyzers, Oscilloscopes, and Multimeters via `sigrok-cli` (FX2lafw 24MHz 8-ch, Saleae clones, DSLogic, etc.).
- `sigrok_capture_and_decode(driver, samplerate, samples, time_ms, channels, protocol_decoder, output_file)` — Capture digital signals and run protocol decoders (`uart`, `i2c`, `spi`, `pwm`, `ws281x`).
- `adb_list_devices()` — List connected Android phones, tablets, or embedded Android boards via `adb`.
- `adb_command(command, device_serial, is_shell, timeout_sec)` — Run `adb shell` commands (e.g., `logcat -d -t 50`, `dumpsys battery`, `input tap`) or host ADB commands (`install app.apk`).

---

## Example Workflows

1. **Automated Crash Loop Debugging:**
   > *"My ESP32 keeps rebooting when I initialize the I2S microphone. Read the serial logs, find why it's crashing, fix the code, and flash it back to the board."*
   The AI calls `list_serial_ports` → `read_serial_logs` (catches the `Guru Meditation Error` & stack trace) → edits your C++ code → calls `compile_and_flash` → calls `read_serial_logs` again to confirm the crash is gone.

2. **Hardware-in-the-Loop Audio & Visual Verification:**
   > *"Send the 'LED_ON' command over serial, take a snapshot from `/dev/video0` to verify the red LED turned on, and play a 1kHz test tone while reading the I2S peak values from serial."*

---

## Troubleshooting Checklist

You can ask the AI to run `check_prerequisites` at any time to automatically diagnose your system.

### 1. `Permission denied: '/dev/ttyUSB0'` on Linux
Add your user to the `dialout` (Debian/Ubuntu) or `uucp` (Arch) group so you can access serial ports without `sudo`:
```bash
# Ubuntu / Debian / Raspberry Pi OS
sudo usermod -aG dialout $USER

# Arch Linux / Manjaro
sudo usermod -aG uucp $USER
```
*(Log out and log back in after running this command for group changes to take effect.)*

### 2. `Port busy` / `Resource temporarily unavailable`
If another serial monitor (`screen`, `minicom`, Arduino IDE) is holding the port, simply ask the AI:
> *"Check what process is locking `/dev/ttyUSB0` and free the port."*
The AI will call `find_port_occupiers` and `free_serial_port` automatically.

### 3. Installing Optional External CLI Toolchains
Install whichever tools match your workflow:
- **PlatformIO**: `uv tool install platformio`
- **esptool**: `uv tool install esptool`
- **Arduino CLI**: `brew install arduino-cli` or via official installer script
- **Logic Analyzer (`sigrok-cli`)**: `sudo apt install sigrok-cli sigrok-firmware-fx2lafw`
- **Android ADB**: `sudo apt install adb`

---

## Running Tests

```bash
uv run pytest -v
```

## License

[MIT](LICENSE)
