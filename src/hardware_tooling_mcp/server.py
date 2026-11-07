"""Main FastMCP entrypoint for the Hardware Tooling Bridge MCP Server."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from hardware_tooling_mcp.tools.audio_media import register_audio_media_tools
from hardware_tooling_mcp.tools.ble_bridge import register_ble_tools
from hardware_tooling_mcp.tools.external_devices import register_external_device_tools
from hardware_tooling_mcp.tools.gpio_bus import register_gpio_bus_tools
from hardware_tooling_mcp.tools.gui_automation import register_gui_automation_tools
from hardware_tooling_mcp.tools.process_manager import register_process_tools
from hardware_tooling_mcp.tools.serial_bridge import register_serial_tools
from hardware_tooling_mcp.tools.toolchains import register_toolchain_tools

mcp = MCPServer(
    "Hardware Tooling",
    instructions=(
        "Embedded & Hardware Tooling Bridge MCP Server. "
        "Provides tools to scan and communicate over USB Serial ports (ESP32, Arduino, Pico, STM32), "
        "Bluetooth Low Energy (BLE) GATT peripherals, "
        "compile and flash firmware (Arduino CLI, PlatformIO, ESP-IDF, esptool, custom CLI), "
        "control GPIO/I2C/SPI via FTDI/USB bridges, "
        "capture hardware board photos via Webcam/USB Microscope, "
        "decode digital signals with Logic Analyzers (sigrok-cli), "
        "control Android/ADB devices, "
        "manage host processes & serial port locks, "
        "automate GUI windows/screenshots/hotkeys, and test audio/media devices (microphones, speakers)."
    ),
)

# Register all hardware and host software tool groups
register_serial_tools(mcp)
register_toolchain_tools(mcp)
register_process_tools(mcp)
register_gpio_bus_tools(mcp)
register_audio_media_tools(mcp)
register_gui_automation_tools(mcp)
register_ble_tools(mcp)
register_external_device_tools(mcp)


def main() -> None:
    """Run the Hardware Tooling MCP Server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
