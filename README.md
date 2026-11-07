# Hardware-Tooling-MCP

**Embedded / Hardware Tooling Bridge (`hardware-tooling-mcp`)** คือ MCP Server ที่เชื่อมโลกของ **ฮาร์ดแวร์จริงที่เสียบอยู่กับคอมพิวเตอร์** และ **ระบบปฏิบัติการ (Host OS)** เข้ากับ AI Agent (เช่น Claude Desktop, Cursor, Cline, Roo Code, Antigravity, หรือ AI CLI ต่างๆ) ผ่าน Model Context Protocol (MCP) แบบ Local `stdio`

```text
[ ผู้ใช้คุยภาษาคน ]
       │
       ▼
[ AI Agent ]
       │ (เรียก MCP Tools: list_serial_ports, read_serial_logs, compile_and_flash, ...)
       ▼
[ Hardware Tooling MCP Bridge (รันแบบ Local stdio บนเครื่องผู้ใช้) ]
       ├── 1. USB / Serial Bridge (pyserial, DTR/RTS Bootloader & Reset, Crash Detector)
       ├── 2. Hardware Flashing & Toolchains (check_prerequisites, arduino-cli, pio, idf.py, esptool)
       ├── 3. Direct GPIO / I2C / SPI (FT232H / FTDI MPSSE & Linux i2c/spidev/gpiochip)
       ├── 4. Process & Port Management (psutil, lsof, ปลดล็อกพอร์ต Serial ที่ค้าง)
       ├── 5. Audio & Media Control (อัดเสียงทดสอบไมค์ + วิเคราะห์ RMS/dBFS, ปรับระดับเสียง, สร้างเสียง Tone)
       ├── 6. GUI & Screen Automation (take_screenshot, send_hotkey)
       ├── 7. Bluetooth Low Energy (BLE) (bleak: scan, GATT inspect, read/write characteristic)
       └── 8. Webcam/Microscope Vision, Logic Analyzer (sigrok-cli) & Android ADB
```

---

## วิธีติดตั้งและใช้งาน (Quick Start)

เนื่องจาก MCP Server ตัวนี้ต้องคุยกับพอร์ต USB/Serial และ OS บนเครื่องโดยตรง จึงทำงานแบบ **Local Transport (`stdio`)** ผู้ใช้สามารถนำ Config JSON ด้านล่างไปวางใน AI Client ที่ใช้งานได้ทันที

### แบบที่ 1: เรียกผ่าน `uvx` จาก GitHub Repository โดยตรง (ไม่ต้อง clone โค้ดเอง)

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

### แบบที่ 2: เรียกผ่าน `uvx` จาก PyPI (เมื่อเผยแพร่บน PyPI แล้ว)

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

### แบบที่ 3: รันจากโฟลเดอร์ที่ Clone ลงเครื่อง (Local Development)

```bash
git clone https://github.com/Pheem49/Hardware-Tooling-MCP.git
cd Hardware-Tooling-MCP
uv sync
```

จากนั้นตั้งค่าใน MCP Client:

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

## ตำแหน่งไฟล์ตั้งค่าของแต่ละ AI Client

นำ JSON ด้านบนไปวางในไฟล์ Config ตามโปรแกรมที่คุณใช้งาน:

| AI Client | ตำแหน่งไฟล์ตั้งค่า (Config Path) |
| :--- | :--- |
| **Claude Desktop (Linux)** | `~/.config/Claude/claude_desktop_config.json` |
| **Claude Desktop (macOS)** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Claude Desktop (Windows)** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Cursor** | `.cursor/mcp.json` (ระดับโปรเจกต์) หรือ `~/.cursor/mcp.json` (ระดับ Global) |
| **Cline / Roo Code (VS Code)** | เปิดแถบ MCP Servers ใน Extension แล้วเลือก **Edit MCP Settings** |

---

## ชุด Tools ทั้งหมด (33 Tools แบ่งตาม 8 โมดูล)

### 1. USB / Serial Bridge (`tools/serial_bridge.py`)
- `list_serial_ports(include_symlinks, hide_phantom_ttys)` — สแกนพอร์ต USB Serial ทั้งหมด พร้อมระบุ VID/PID และทายชนิดบอร์ดอัตโนมัติ (ESP32, Arduino, Pico, STM32, CP210x, CH340, FTDI)
- `read_serial_logs(port, baudrate, timeout_sec, max_lines, stop_on_pattern, stop_on_crash_dump, reset_before_read)` — อ่าน Serial Monitor พร้อมตรวจจับ Crash Dump อัตโนมัติ (`Guru Meditation Error`, `Backtrace:`, `Brownout detector`, `HardFault`)
- `send_serial_command(port, data, baudrate, encoding, line_ending, read_response_sec)` — ส่งข้อความ (`utf-8`/`ascii`) หรือชุด Byte ดิบ (`hex` เช่น `"AA 55 01 FF"`) เข้าบอร์ดและอ่านผลตอบกลับทันที
- `toggle_dtr_rts(port, mode, dtr, rts, pulse_ms)` — สั่งรีเซ็ตบอร์ด (`mode="reset"`) หรือบังคับเข้าโหมดแฟลช ESP32 (`mode="esp32_bootloader"`) ผ่านขา DTR/RTS โดยไม่ต้องกดปุ่มบนบอร์ด

### 2. Hardware Flashing, Toolchains & Readiness (`tools/toolchains.py`)
- `check_prerequisites()` — **ตรวจสอบความพร้อมของเครื่องผู้ใช้ครบวงจร**: เช็คสิทธิ์กลุ่มพอร์ต Serial บน Linux (`dialout`/`uucp`), เช็ค Toolchain ที่ติดตั้งแล้ว และแนะนำคำสั่งติดตั้งหากยังขาดเครื่องมือใด
- `check_toolchains()` — ตรวจสอบเวอร์ชันและ path ของ `arduino-cli`, `pio`, `idf.py`, `esptool`, `openocd`, `avrdude`, `dfu-util`, `picotool`
- `compile_and_flash(project_path, toolchain, port, board_fqbn_or_env, action, extra_args, timeout_sec)` — คอมไพล์และอัปโหลดเฟิร์มแวร์ด้วย `arduino-cli`, `platformio`, หรือ `esp-idf` (รองรับ `toolchain="auto"` ตรวจจับจากไฟล์โปรเจกต์อัตโนมัติ)
- `esptool_command(operation, port, baudrate, chip, flash_offset, binary_path, extra_args)` — เรียก `esptool` โดยตรงเพื่อเช็ค `chip_id`, `flash_id`, `read_mac`, `erase_flash`, หรือ `write_flash`
- `run_custom_toolchain(command, working_directory, timeout_sec)` — รันคำสั่ง CLI เฉพาะทางอื่นๆ (เช่น `make flash`, `west build`, `cargo embed`)

### 3. Direct GPIO / I2C / SPI (`tools/gpio_bus.py`)
- `scan_hardware_bridges()` — ค้นหาชิปแปลง USB Bridge เช่น FTDI (`FT232H`, `FT2232H`) และอุปกรณ์ `/dev/i2c-*`, `/dev/spidev*`, `/dev/gpiochip*` บน Linux
- `ftdi_gpio_control(ftdi_url, direction_mask, write_value)` — สั่ง High/Low หรืออ่านค่าขา GPIO 8-bit โดยตรงผ่าน FTDI
- `ftdi_i2c_scan(ftdi_url, frequency_hz)` — สแกนหา I2C Slave Address บนบัส
- `ftdi_i2c_transfer(address, ftdi_url, register_addr, write_hex, read_length, frequency_hz)` — อ่าน/เขียน Register ของเซนเซอร์ I2C โดยตรง
- `ftdi_spi_transfer(write_hex, read_length, ftdi_url, cs, freq_hz, mode)` — รับ/ส่งข้อมูลผ่านบัส SPI โดยตรง

### 4. Process & Port Management (`tools/process_manager.py`)
- `list_processes(filter_name, limit)` — ตรวจสอบโปรเซสที่กำลังรันอยู่บนเครื่อง
- `find_port_occupiers(port)` — เช็คว่าโปรแกรมใดกำลังแย่งใช้งานพอร์ต Serial (แก้ปัญหา `Port busy`)
- `free_serial_port(port, force)` — สั่งปิดโปรเซสที่ล็อกพอร์ต Serial อยู่โดยอัตโนมัติเพื่อให้พร้อมแฟลชหรือเปิด Serial Monitor
- `start_process(command, args, cwd, background, timeout_sec)` — เปิดโปรแกรมหรือรัน CLI utility (ทั้งแบบรอผลและแบบ Background)
- `kill_process(pid, process_name, force)` — สั่งปิดโปรแกรมตาม PID หรือชื่อโปรเซส

### 5. Audio & Media Control (`tools/audio_media.py`)
- `list_media_devices()` — แสดงรายการไมโครโฟน ลำโพง (ALSA / PipeWire / PulseAudio) และกล้อง Webcam (`/dev/video*`)
- `set_audio_volume(target, volume_percent, mute, device_id)` — ปรับระดับเสียงหรือ Mute/Unmute ลำโพง (`sink`) และไมโครโฟน (`source`)
- `record_audio_sample(duration_sec, output_path, sample_rate, channels, alsa_device)` — อัดเสียงจากไมโครโฟนพร้อมคำนวณค่าสถิติสัญญาณเสียง (`rms_dbfs`, `peak_dbfs`, `is_silent`) เพื่อเช็คว่ามีเสียงออกจริงหรือไม่
- `play_test_tone(frequency_hz, duration_sec)` — สร้างและเล่นเสียง Sine Wave ความถี่ที่กำหนดออกลำโพงเพื่อใช้ทดสอบไมโครโฟนบนบอร์ด

### 6. GUI & Screen Automation (`tools/gui_automation.py`)
- `take_screenshot(output_path, region)` — แคปภาพหน้าจอทั้งหมดหรือเฉพาะพื้นที่ (`x,y,width,height`) ส่งให้ AI ดูหน้าต่างโปรแกรมหรือ Error Dialog
- `send_hotkey(keys, window_title, delay_ms)` — ส่งคีย์ลัดคีย์บอร์ด (เช่น `ctrl+shift+b`, `ctrl+s`) ไปยังหน้าต่างโปรแกรมที่กำหนดผ่าน `xdotool`

### 7. Bluetooth Low Energy (BLE) (`tools/ble_bridge.py`)
- `ble_scan_devices(timeout_sec, name_filter)` — สแกนหาอุปกรณ์ BLE รอบข้าง (ESP32 BLE, nRF52, เซนเซอร์ไร้สาย) พร้อมค่า RSSI และ Service UUIDs
- `ble_inspect_gatt(address, timeout_sec)` — เชื่อมต่ออุปกรณ์ BLE เพื่อดูรายการ GATT Services และ Characteristics ทั้งหมด
- `ble_read_write_characteristic(address, characteristic_uuid, write_data, encoding, read_after_write, with_response, timeout_sec)` — อ่านหรือส่งข้อมูล (ข้อความหรือ Hex Byte) ไปยัง GATT Characteristic ของบอร์ดไร้สาย

### 8. Webcam/Microscope Vision, Logic Analyzer & Android ADB (`tools/external_devices.py`)
- `capture_camera_snapshot(device, output_path, resolution, skip_warmup_frames)` — สั่งถ่ายภาพบอร์ดจริงบนโต๊ะผ่านกล้อง Webcam หรือกล้องจุลทรรศน์ USB (`/dev/video*`) เพื่อให้ AI ตรวจดูไฟ LED, หน้าจอ OLED/LCD หรือจุดบัดกรีบน PCB
- `sigrok_scan_devices()` — สแกนหา Logic Analyzer / Oscilloscope ที่เสียบอยู่ผ่าน `sigrok-cli` (เช่น FX2lafw 24MHz 8-ch, Saleae clones, DSLogic)
- `sigrok_capture_and_decode(driver, samplerate, samples, time_ms, channels, protocol_decoder, output_file)` — ดึงสัญญาณพัลส์ดิจิทัลจริงและถอดรหัสโปรโตคอล (`uart`, `i2c`, `spi`, `pwm`) อัตโนมัติ
- `adb_list_devices()` — แสดงรายการโทรศัพท์หรือบอร์ด Android ที่เสียบสาย USB ผ่าน `adb`
- `adb_command(command, device_serial, is_shell, timeout_sec)` — รันคำสั่ง `adb shell` (เช่นดึง `logcat`, เช็คแบตเตอรี่, สั่งกดหน้าจอ) หรือสั่งติดตั้งแอป `.apk`

---

## การแก้ไขปัญหาที่พบบ่อย (Troubleshooting Checklist)

คุณสามารถบอกให้ AI เรียก tool `check_prerequisites` เพื่อตรวจสอบเครื่องของคุณอัตโนมัติได้ทันที หรือตรวจสอบตามรายการด้านล่าง:

### 1. ปัญหา `Permission denied: '/dev/ttyUSB0'` บน Linux
ผู้ใช้ Linux มักไม่มีสิทธิ์เข้าถึงพอร์ต Serial ในครั้งแรก ต้องเพิ่ม user เข้ากลุ่ม `dialout` (Debian/Ubuntu/Mint) หรือ `uucp` (Arch/Manjaro):
```bash
# สำหรับ Ubuntu / Debian / Raspberry Pi OS
sudo usermod -aG dialout $USER

# สำหรับ Arch Linux / Manjaro
sudo usermod -aG uucp $USER
```
*(หลังจากรันคำสั่งแล้ว ต้อง **Log out แล้ว Log in ใหม่** หรือรีสตาร์ทเครื่อง 1 ครั้ง)*

### 2. ปัญหาพอร์ตไม่ว่าง (`Port busy` / `Resource temporarily unavailable`)
มักเกิดจากเปิด Serial Monitor ใน Arduino IDE, VS Code, หรือ `minicom`/`screen` ค้างไว้ สามารถสั่ง AI ว่า:
> *"ช่วยเช็คว่าโปรแกรมอะไรแย่งพอร์ต `/dev/ttyUSB0` อยู่ แล้วสั่งปิดให้หน่อย"*
AI จะเรียก `find_port_occupiers` และ `free_serial_port` จัดการให้ทันทีโดยไม่ต้องสลับหน้าต่างไปหาปิดเอง

### 3. การติดตั้ง Toolchain ภายนอก (สำหรับสั่ง Compile & Flash)
เลือกติดตั้งเฉพาะตัวที่คุณใช้งาน:
- **PlatformIO**: `uv tool install platformio` หรือ `pipx install platformio`
- **esptool**: `uv tool install esptool`
- **Arduino CLI**: `brew install arduino-cli` หรือดาวน์โหลดจากเว็บไซต์ Arduino
