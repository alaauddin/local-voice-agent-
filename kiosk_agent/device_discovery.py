"""Discover cooperative controllers on the local IPv4 network."""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

IDENTITY_PATH = "/identity"
IDENTITY_PROTOCOL = "wazen-device-identity/1"
logger = logging.getLogger(__name__)


class DeviceDiscoveryError(RuntimeError):
    pass


def _local_scan_network() -> tuple[
    ipaddress.IPv4Network,
    ipaddress.IPv4Address | None,
    str,
]:
    configured_network = str(
        getattr(settings, "DEVICE_DISCOVERY_NETWORK", "") or ""
    ).strip()
    if configured_network:
        try:
            network = ipaddress.IPv4Network(configured_network, strict=False)
        except ValueError as exc:
            raise DeviceDiscoveryError(
                f"Invalid DEVICE_DISCOVERY_NETWORK '{configured_network}': {exc}"
            ) from exc
        logger.info("Using configured device discovery network: %s", network)
        return network, None, "configured"

    # Keep this import lazy: merely loading Django must not inspect host networking.
    import netifaces

    try:
        gateways = netifaces.gateways()
        default = gateways.get("default", {}).get(netifaces.AF_INET)
        addresses = []

        for interface in netifaces.interfaces():
            if interface == "lo":
                continue
            for item in netifaces.ifaddresses(interface).get(netifaces.AF_INET, []):
                raw_ip = item.get("addr")
                netmask = item.get("netmask")
                if not raw_ip or not netmask:
                    continue
                ip = ipaddress.IPv4Address(raw_ip)
                if ip.is_loopback or ip.is_link_local:
                    continue
                network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                addresses.append((network, ip, interface))
                logger.debug(
                    "Found IPv4 interface: interface=%s ip=%s network=%s",
                    interface,
                    ip,
                    network,
                )
    except (OSError, PermissionError, ValueError) as exc:
        raise DeviceDiscoveryError(f"Could not inspect local IPv4 interfaces: {exc}") from exc

    if not addresses:
        raise DeviceDiscoveryError("No usable local IPv4 interface was found.")

    if default:
        default_interface = default[1]
        for network, ip, interface in addresses:
            if interface == default_interface:
                return network, ip, interface

    physical = [
        item
        for item in addresses
        if item[2].startswith(("wl", "en", "eth"))
    ]
    return (physical or addresses)[0]


def _probe_identity(ip: str, timeout: float) -> dict | None:
    logger.debug("Probing device identity: ip=%s path=%s", ip, IDENTITY_PATH)
    connection = http.client.HTTPConnection(ip, 80, timeout=timeout)
    try:
        connection.request(
            "GET",
            IDENTITY_PATH,
            headers={
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "WazenDeviceSync/1.0",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            return None
        body = response.read(16_385)
        if len(body) > 16_384:
            return None
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, http.client.HTTPException):
        return None
    finally:
        connection.close()

    if not isinstance(payload, dict) or payload.get("protocol") != IDENTITY_PROTOCOL:
        return None

    name = payload.get("device_name") or payload.get("name")
    device_type = payload.get("device_type") or payload.get("type")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(device_type, str) or not device_type.strip():
        return None

    identity = {
        "name": name.strip(),
        "type": device_type.strip(),
        "ip": ip,
        "device_id": str(payload.get("device_id") or "")[:120],
        "hostname": str(payload.get("hostname") or "")[:253],
    }
    logger.info(
        "Discovered identity device: ip=%s name=%s type=%s",
        identity["ip"],
        identity["name"],
        identity["type"],
    )
    return identity


def discover_identity_devices() -> list[dict]:
    """Probe the local subnet and return devices implementing our identity contract."""
    network, local_ip, interface = _local_scan_network()
    max_hosts = max(1, int(getattr(settings, "DEVICE_DISCOVERY_MAX_HOSTS", 1024)))

    # Avoid accidentally scanning a very large corporate/VPN network. For a broad
    # interface subnet, limit discovery to the local address's /24.
    if network.num_addresses - 2 > max_hosts:
        if local_ip is None:
            raise DeviceDiscoveryError(
                f"Configured network {network} exceeds DEVICE_DISCOVERY_MAX_HOSTS="
                f"{max_hosts}. Configure a smaller subnet or raise the limit."
            )
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)

    targets = []
    for ip in network.hosts():
        if local_ip is not None and ip == local_ip:
            continue
        targets.append(str(ip))
        if len(targets) >= max_hosts:
            break
    timeout = max(
        0.05,
        float(getattr(settings, "DEVICE_DISCOVERY_TIMEOUT_SECONDS", 0.4)),
    )
    workers = max(1, int(getattr(settings, "DEVICE_DISCOVERY_WORKERS", 64)))

    logger.info(
        "Starting device discovery: interface=%s local_ip=%s network=%s targets=%s",
        interface,
        local_ip or "container-routed",
        network,
        len(targets),
    )

    with ThreadPoolExecutor(max_workers=min(workers, len(targets) or 1)) as executor:
        results = executor.map(lambda ip: _probe_identity(ip, timeout), targets)
        devices = [result for result in results if result]

    devices = sorted(devices, key=lambda item: ipaddress.ip_address(item["ip"]))
    logger.info(
        "Device discovery complete: found=%s ips=%s",
        len(devices),
        ",".join(device["ip"] for device in devices) or "none",
    )
    return devices
