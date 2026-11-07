"""Bluetooth Low Energy (BLE) hardware communication tools via Bleak."""

from __future__ import annotations

import re
from typing import Any

from mcp.server.mcpserver import MCPServer


def register_ble_tools(mcp: MCPServer) -> None:
    """Register Bluetooth Low Energy (BLE) scanning and GATT read/write tools."""

    @mcp.tool()
    async def ble_scan_devices(
        timeout_sec: float = 5.0,
        name_filter: str | None = None,
    ) -> dict[str, Any]:
        """Scan for nearby Bluetooth Low Energy (BLE) devices (ESP32, nRF52, sensors, beacons).

        Args:
            timeout_sec: Scan duration in seconds (1.0 to 20.0, default 5.0).
            name_filter: Optional case-insensitive substring to filter by device name or address.
        """
        timeout_sec = max(1.0, min(timeout_sec, 20.0))
        try:
            from bleak import BleakScanner

            discovered = await BleakScanner.discover(timeout=timeout_sec, return_adv=True)
            devices_list: list[dict[str, Any]] = []
            needle = name_filter.lower() if name_filter else None

            for address, (dev, adv) in discovered.items():
                name = dev.name or adv.local_name or "Unknown"
                if needle and needle not in name.lower() and needle not in address.lower():
                    continue
                devices_list.append(
                    {
                        "address": address,
                        "name": name,
                        "rssi": adv.rssi,
                        "service_uuids": list(adv.service_uuids or []),
                        "manufacturer_data": {
                            f"0x{k:04X}": v.hex(" ") for k, v in (adv.manufacturer_data or {}).items()
                        },
                    }
                )

            devices_list.sort(key=lambda x: x.get("rssi") or -999, reverse=True)
            return {
                "success": True,
                "count": len(devices_list),
                "devices": devices_list,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "hint": "Ensure Bluetooth adapter is powered on (`bluetoothctl power on`) and BlueZ/D-Bus is running.",
            }

    @mcp.tool()
    async def ble_inspect_gatt(
        address: str,
        timeout_sec: float = 10.0,
    ) -> dict[str, Any]:
        """Connect to a BLE device and list all GATT Services, Characteristics, and their properties.

        Args:
            address: BLE MAC address (Linux/Windows, e.g. 'AA:BB:CC:DD:EE:FF') or UUID (macOS).
            timeout_sec: Connection timeout in seconds (default 10.0).
        """
        try:
            from bleak import BleakClient

            async with BleakClient(address, timeout=timeout_sec) as client:
                services_info: list[dict[str, Any]] = []
                for service in client.services:
                    chars_info: list[dict[str, Any]] = []
                    for char in service.characteristics:
                        chars_info.append(
                            {
                                "uuid": char.uuid,
                                "handle": char.handle,
                                "description": char.description,
                                "properties": list(char.properties),
                            }
                        )
                    services_info.append(
                        {
                            "uuid": service.uuid,
                            "description": service.description,
                            "characteristics": chars_info,
                        }
                    )

                return {
                    "success": True,
                    "address": address,
                    "is_connected": client.is_connected,
                    "service_count": len(services_info),
                    "services": services_info,
                }
        except Exception as exc:
            return {
                "success": False,
                "address": address,
                "error": str(exc),
            }

    @mcp.tool()
    async def ble_read_write_characteristic(
        address: str,
        characteristic_uuid: str,
        write_data: str | None = None,
        encoding: str = "utf-8",
        read_after_write: bool = True,
        with_response: bool = True,
        timeout_sec: float = 10.0,
    ) -> dict[str, Any]:
        """Read from and/or write to a GATT Characteristic on a BLE peripheral.

        Args:
            address: BLE MAC address or UUID of the target board/sensor.
            characteristic_uuid: UUID of the GATT characteristic to read/write.
            write_data: Optional payload to write. If None, performs a read-only operation.
            encoding: 'utf-8', 'ascii', or 'hex' (e.g. '01 FF 0A') when writing data.
            read_after_write: Whether to read the characteristic value back after writing.
            with_response: Request GATT write-with-response (True) or write-without-response (False).
            timeout_sec: Connection timeout in seconds (default 10.0).
        """
        try:
            from bleak import BleakClient

            payload: bytes | None = None
            if write_data is not None:
                if encoding.lower() == "hex":
                    cleaned = re.sub(r"[^0-9a-fA-F]", "", write_data)
                    if len(cleaned) % 2 != 0:
                        return {
                            "success": False,
                            "error": "Hex write_data must have an even number of hex digits.",
                        }
                    payload = bytes.fromhex(cleaned)
                else:
                    payload = write_data.encode(encoding)

            async with BleakClient(address, timeout=timeout_sec) as client:
                if payload is not None:
                    await client.write_gatt_char(
                        characteristic_uuid, payload, response=with_response
                    )

                read_bytes: bytes | None = None
                if payload is None or read_after_write:
                    try:
                        read_bytes = bytes(await client.read_gatt_char(characteristic_uuid))
                    except Exception:
                        read_bytes = None

                return {
                    "success": True,
                    "address": address,
                    "characteristic_uuid": characteristic_uuid,
                    "written_hex": payload.hex(" ") if payload is not None else None,
                    "read_hex": read_bytes.hex(" ") if read_bytes is not None else None,
                    "read_text": (
                        read_bytes.decode("utf-8", errors="replace")
                        if read_bytes is not None
                        else None
                    ),
                    "read_bytes": list(read_bytes) if read_bytes is not None else None,
                }
        except Exception as exc:
            return {
                "success": False,
                "address": address,
                "characteristic_uuid": characteristic_uuid,
                "error": str(exc),
            }
