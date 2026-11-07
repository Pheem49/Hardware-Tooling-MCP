"""Direct GPIO, I2C, and SPI hardware control via USB-to-Hardware bridges (FT232H/FTDI & Linux bus devices)."""

from __future__ import annotations

import glob
import re
from typing import Any

from mcp.server.mcpserver import MCPServer


def _parse_hex_bytes(data: str) -> bytes:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", data)
    if len(cleaned) % 2 != 0:
        raise ValueError("Hex data string must have an even number of hex digits.")
    return bytes.fromhex(cleaned)


def register_gpio_bus_tools(mcp: MCPServer) -> None:
    """Register direct GPIO, I2C, and SPI hardware bridge tools on the FastMCP instance."""

    @mcp.tool()
    def scan_hardware_bridges() -> dict[str, Any]:
        """Discover connected USB-to-GPIO/I2C/SPI bridges (FT232H, FT2232H, CH341) and Linux bus devices.

        Returns FTDI URLs (e.g. 'ftdi://ftdi:232h/1') and Linux '/dev/i2c-*', '/dev/spidev*',
        and '/dev/gpiochip*' nodes.
        """
        ftdi_urls: list[str] = []
        ftdi_error: str | None = None
        try:
            from pyftdi.ftdi import Ftdi

            devices = Ftdi.list_devices()
            for dev_desc, interfaces in devices:
                vid = dev_desc.vid
                pid = dev_desc.pid
                sn = dev_desc.sn or ""
                desc = dev_desc.description or "FTDI"
                for iface in range(1, interfaces + 1):
                    ftdi_urls.append(
                        f"ftdi://0x{vid:04x}:0x{pid:04x}:{sn}/{iface} ({desc})"
                    )
        except Exception as exc:
            ftdi_error = str(exc)

        linux_i2c = sorted(glob.glob("/dev/i2c-*"))
        linux_spi = sorted(glob.glob("/dev/spidev*"))
        linux_gpio = sorted(glob.glob("/dev/gpiochip*"))

        return {
            "ftdi_devices": ftdi_urls,
            "ftdi_note": ftdi_error,
            "linux_i2c_buses": linux_i2c,
            "linux_spi_devices": linux_spi,
            "linux_gpio_chips": linux_gpio,
        }

    @mcp.tool()
    def ftdi_gpio_control(
        ftdi_url: str = "ftdi:///1",
        direction_mask: int = 0xFF,
        write_value: int | None = None,
    ) -> dict[str, Any]:
        """Read or write GPIO pins directly on an FTDI USB bridge (e.g. FT232H, FT2232H).

        Args:
            ftdi_url: PyFtdi device URL (default 'ftdi:///1' for first connected FTDI device).
            direction_mask: 8-bit bitmask where 1 = Output, 0 = Input (e.g., 0xFF = all outputs, 0x01 = pin 0 output).
            write_value: Optional 8-bit value to drive on output pins (0x00 to 0xFF). Always reads back current pin states.
        """
        try:
            from pyftdi.gpio import GpioAsyncController

            gpio = GpioAsyncController()
            gpio.configure(ftdi_url, direction=direction_mask & 0xFF)
            try:
                if write_value is not None:
                    gpio.write(write_value & direction_mask & 0xFF)
                read_val = gpio.read()
                pin_states = {f"D{bit}": bool((read_val >> bit) & 1) for bit in range(8)}
                return {
                    "success": True,
                    "ftdi_url": ftdi_url,
                    "direction_mask_hex": f"0x{direction_mask & 0xFF:02X}",
                    "written_hex": f"0x{write_value & 0xFF:02X}" if write_value is not None else None,
                    "read_value_hex": f"0x{read_val:02X}",
                    "pin_states": pin_states,
                }
            finally:
                gpio.close()
        except Exception as exc:
            return {
                "success": False,
                "ftdi_url": ftdi_url,
                "error": str(exc),
            }

    @mcp.tool()
    def ftdi_i2c_scan(
        ftdi_url: str = "ftdi:///1",
        frequency_hz: int = 100_000,
    ) -> dict[str, Any]:
        """Scan an I2C bus connected via an FT232H/FT2232H MPSSE bridge for active slave addresses.

        Args:
            ftdi_url: PyFtdi URL (e.g., 'ftdi:///1').
            frequency_hz: I2C clock frequency in Hz (default 100000 for 100kHz standard mode).
        """
        try:
            from pyftdi.i2c import I2cController, I2cNackError

            i2c = I2cController()
            i2c.configure(ftdi_url, frequency=frequency_hz)
            found_addresses: list[str] = []
            try:
                for addr in range(0x08, 0x78):
                    port = i2c.get_port(addr)
                    try:
                        port.read(0)
                        found_addresses.append(f"0x{addr:02X}")
                    except I2cNackError:
                        continue
                return {
                    "success": True,
                    "ftdi_url": ftdi_url,
                    "frequency_hz": frequency_hz,
                    "devices_found": len(found_addresses),
                    "addresses": found_addresses,
                }
            finally:
                i2c.terminate()
        except Exception as exc:
            return {
                "success": False,
                "ftdi_url": ftdi_url,
                "error": str(exc),
            }

    @mcp.tool()
    def ftdi_i2c_transfer(
        address: int,
        ftdi_url: str = "ftdi:///1",
        register_addr: int | None = None,
        write_hex: str | None = None,
        read_length: int = 0,
        frequency_hz: int = 100_000,
    ) -> dict[str, Any]:
        """Read and/or write registers on an I2C slave device via an FT232H/FTDI bridge.

        Args:
            address: 7-bit I2C slave address (e.g., 0x68 for MPU6050, 0x3C for SSD1306 OLED, 0x76 for BME280).
            ftdi_url: PyFtdi device URL (default 'ftdi:///1').
            register_addr: Optional 8-bit register address to read from or write to.
            write_hex: Optional hex bytes string to write (e.g., '01 FF').
            read_length: Number of bytes to read back (0 for write-only).
            frequency_hz: I2C clock speed in Hz (default 100000).
        """
        try:
            from pyftdi.i2c import I2cController

            payload = _parse_hex_bytes(write_hex) if write_hex else b""
            i2c = I2cController()
            i2c.configure(ftdi_url, frequency=frequency_hz)
            try:
                port = i2c.get_port(address)
                read_data = b""
                if register_addr is not None:
                    if payload:
                        port.write_to(register_addr, payload)
                    if read_length > 0:
                        read_data = bytes(port.read_from(register_addr, read_length))
                else:
                    if payload and read_length > 0:
                        read_data = bytes(port.exchange(payload, read_length))
                    elif payload:
                        port.write(payload)
                    elif read_length > 0:
                        read_data = bytes(port.read(read_length))

                return {
                    "success": True,
                    "address_hex": f"0x{address:02X}",
                    "register_hex": f"0x{register_addr:02X}" if register_addr is not None else None,
                    "written_hex": payload.hex(" ") if payload else None,
                    "read_length": len(read_data),
                    "read_hex": read_data.hex(" "),
                    "read_bytes": list(read_data),
                }
            finally:
                i2c.terminate()
        except Exception as exc:
            return {
                "success": False,
                "address_hex": f"0x{address:02X}",
                "error": str(exc),
            }

    @mcp.tool()
    def ftdi_spi_transfer(
        write_hex: str,
        read_length: int = 0,
        ftdi_url: str = "ftdi:///1",
        cs: int = 0,
        freq_hz: int = 1_000_000,
        mode: int = 0,
    ) -> dict[str, Any]:
        """Perform an SPI exchange/transfer via an FT232H/FTDI MPSSE bridge.

        Args:
            write_hex: Hex bytes string to transmit over MOSI (e.g., '9F' to read JEDEC Flash ID).
            read_length: Number of bytes to read back on MISO after writing.
            ftdi_url: PyFtdi device URL (default 'ftdi:///1').
            cs: Chip Select index (0..3, default 0).
            freq_hz: SPI clock frequency in Hz (default 1MHz).
            mode: SPI mode (0, 1, 2, or 3).
        """
        try:
            from pyftdi.spi import SpiController

            out_bytes = _parse_hex_bytes(write_hex)
            spi = SpiController()
            spi.configure(ftdi_url)
            try:
                slave = spi.get_port(cs=cs, freq=freq_hz, mode=mode)
                in_bytes = bytes(slave.exchange(out_bytes, readlen=read_length))
                return {
                    "success": True,
                    "ftdi_url": ftdi_url,
                    "cs": cs,
                    "mode": mode,
                    "freq_hz": freq_hz,
                    "tx_hex": out_bytes.hex(" "),
                    "rx_hex": in_bytes.hex(" "),
                    "rx_bytes": list(in_bytes),
                }
            finally:
                spi.terminate()
        except Exception as exc:
            return {
                "success": False,
                "ftdi_url": ftdi_url,
                "error": str(exc),
            }
