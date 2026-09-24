import argparse
import http.client
import ipaddress
import json
import secrets
import socket
import struct
from concurrent.futures import ThreadPoolExecutor

import netifaces
from scapy.data import MANUFDB


COMMON_TCP_SERVICES = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    53: "DNS",
    80: "HTTP",
    139: "NetBIOS",
    443: "HTTPS",
    445: "SMB",
    515: "Printer (LPD)",
    554: "Camera/stream (RTSP)",
    631: "Printer (IPP)",
    1883: "MQTT",
    5357: "Web Services Discovery",
    8008: "Chromecast/HTTP",
    8009: "Chromecast",
    8080: "HTTP alternate",
    8443: "HTTPS alternate",
    8883: "MQTT TLS",
    9100: "Printer",
    32400: "Plex",
    62078: "Apple device sync",
}

IDENTITY_PATH = "/identity"
IDENTITY_PROTOCOL = "wazen-device-identity/1"


def get_ipv4_interfaces():
    interfaces = []

    for interface in netifaces.interfaces():
        if interface == "lo":
            continue

        for info in netifaces.ifaddresses(interface).get(netifaces.AF_INET, []):
            ip = info.get("addr")
            netmask = info.get("netmask")
            if not ip or not netmask:
                continue

            address = ipaddress.ip_address(ip)
            if address.is_loopback or address.is_link_local:
                continue

            network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
            interfaces.append({
                "interface": interface,
                "ip": ip,
                "network": str(network),
            })

    return interfaces


def get_network(requested_interface=None):
    gateway_info = netifaces.gateways()
    default_ipv4 = gateway_info.get("default", {}).get(netifaces.AF_INET)

    if requested_interface:
        candidates = [
            item
            for item in get_ipv4_interfaces()
            if item["interface"] == requested_interface
        ]
        if not candidates:
            available = ", ".join(
                sorted({item["interface"] for item in get_ipv4_interfaces()})
            ) or "none"
            raise RuntimeError(
                f"Interface '{requested_interface}' has no usable IPv4 address. "
                f"Available IPv4 interfaces: {available}"
            )
        selected = candidates[0]
    elif default_ipv4:
        gateway_ip, interface = default_ipv4[:2]
        candidates = [
            item
            for item in get_ipv4_interfaces()
            if item["interface"] == interface
        ]
        if not candidates:
            raise RuntimeError(
                f"Default interface '{interface}' has no usable IPv4 address."
            )
        selected = candidates[0]
    else:
        candidates = get_ipv4_interfaces()
        if not candidates:
            raise RuntimeError(
                "No usable IPv4 network was found. This may be an IPv6-only network; "
                "ARP discovery works only on IPv4 networks."
            )

        physical_prefixes = ("wl", "en", "eth")
        physical = [
            item
            for item in candidates
            if item["interface"].startswith(physical_prefixes)
        ]
        selected = (physical or candidates)[0]
        print(
            "No IPv4 default gateway was reported; "
            f"using {selected['interface']} ({selected['ip']})."
        )

        if len(candidates) > 1:
            choices = ", ".join(
                f"{item['interface']}={item['network']}" for item in candidates
            )
            print(f"Other IPv4 interfaces: {choices}")
            print("Use --interface NAME if the automatically selected interface is wrong.")

    interface = selected["interface"]
    network = selected["network"]
    gateway_ip = None

    if default_ipv4 and default_ipv4[1] == interface:
        gateway_ip = default_ipv4[0]
    else:
        for gateway in gateway_info.get(netifaces.AF_INET, []):
            if len(gateway) >= 2 and gateway[1] == interface:
                gateway_ip = gateway[0]
                break

    return network, interface, gateway_ip


def get_reverse_dns_name(ip):
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror):
        return None


def encode_dns_name(name):
    return b"".join(
        bytes([len(label)]) + label.encode("ascii")
        for label in name.rstrip(".").split(".")
    ) + b"\x00"


def read_dns_name(message, offset):
    labels = []
    next_offset = None
    visited = set()

    while True:
        if offset >= len(message) or offset in visited:
            raise ValueError("Invalid DNS name")
        visited.add(offset)

        length = message[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(message):
                raise ValueError("Invalid DNS compression pointer")
            if next_offset is None:
                next_offset = offset + 2
            offset = ((length & 0x3F) << 8) | message[offset + 1]
            continue

        offset += 1
        if length == 0:
            return ".".join(labels), next_offset or offset
        if length > 63 or offset + length > len(message):
            raise ValueError("Invalid DNS label")

        labels.append(message[offset:offset + length].decode("utf-8", errors="replace"))
        offset += length


def get_mdns_name(ip, timeout=0.6):
    reverse_name = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    query = (
        struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
        + encode_dns_name(reverse_name)
        + struct.pack("!HH", 12, 0x8001)  # PTR query requesting a unicast response
    )

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(query, ("224.0.0.251", 5353))
            response, _ = sock.recvfrom(9000)

        _, _, question_count, answer_count, authority_count, additional_count = (
            struct.unpack_from("!HHHHHH", response)
        )
        offset = 12

        for _ in range(question_count):
            _, offset = read_dns_name(response, offset)
            offset += 4

        for _ in range(answer_count + authority_count + additional_count):
            _, offset = read_dns_name(response, offset)
            record_type, _, _, data_length = struct.unpack_from("!HHIH", response, offset)
            offset += 10

            if record_type == 12:
                name, _ = read_dns_name(response, offset)
                if name:
                    return name.rstrip(".")
            offset += data_length
    except (OSError, ValueError, struct.error):
        pass

    return None


def get_netbios_name(ip, timeout=0.6):
    raw_name = b"*" + (b"\x00" * 15)
    encoded_name = b"".join(
        bytes((ord("A") + (byte >> 4), ord("A") + (byte & 0x0F)))
        for byte in raw_name
    )
    transaction_id = secrets.randbits(16)
    query = (
        struct.pack("!HHHHHH", transaction_id, 0, 1, 0, 0, 0)
        + bytes([len(encoded_name)])
        + encoded_name
        + b"\x00"
        + struct.pack("!HH", 0x21, 1)
    )

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(query, (ip, 137))
            response, _ = sock.recvfrom(4096)

        response_id, _, question_count, answer_count, _, _ = struct.unpack_from(
            "!HHHHHH", response
        )
        if response_id != transaction_id:
            return None

        offset = 12
        for _ in range(question_count):
            _, offset = read_dns_name(response, offset)
            offset += 4

        for _ in range(answer_count):
            _, offset = read_dns_name(response, offset)
            record_type, _, _, data_length = struct.unpack_from("!HHIH", response, offset)
            offset += 10
            data_end = offset + data_length

            if record_type == 0x21 and offset < len(response):
                name_count = response[offset]
                offset += 1
                for _ in range(name_count):
                    if offset + 18 > data_end:
                        break
                    name = response[offset:offset + 15].decode("ascii", errors="ignore").strip()
                    suffix = response[offset + 15]
                    flags = struct.unpack_from("!H", response, offset + 16)[0]
                    offset += 18
                    if name and suffix == 0x00 and not flags & 0x8000:
                        return name

            offset = data_end
    except (OSError, ValueError, struct.error):
        pass

    return None


def get_device_name(ip):
    for method, lookup in (
        ("reverse DNS", get_reverse_dns_name),
        ("mDNS", get_mdns_name),
        ("NetBIOS", get_netbios_name),
    ):
        name = lookup(ip)
        if name:
            return name, method

    return "Unknown", "not advertised"


def request_device_identity(ip, timeout=0.8):
    connection = http.client.HTTPConnection(ip, 80, timeout=timeout)

    try:
        connection.request(
            "GET",
            IDENTITY_PATH,
            headers={
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "WazenDeviceDiscovery/1.0",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            return None

        body = response.read(16_385)
        if len(body) > 16_384:
            return None

        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            return None

        protocol = payload.get("protocol")
        if protocol != IDENTITY_PROTOCOL:
            return None

        device_name = payload.get("device_name") or payload.get("name")
        device_type = payload.get("device_type") or payload.get("type")
        if not isinstance(device_name, str) or not device_name.strip():
            return None
        if not isinstance(device_type, str) or not device_type.strip():
            return None

        identity = {
            "protocol": protocol,
            "name": device_name.strip(),
            "type": device_type.strip(),
        }

        optional_fields = (
            "device_id",
            "hostname",
            "model",
            "firmware_version",
            "manufacturer",
            "mac",
            "ssid",
            "rssi",
            "uptime_ms",
            "capabilities",
        )
        for field in optional_fields:
            value = payload.get(field)
            if isinstance(value, (str, int, float, bool, list)):
                identity[field] = value

        return identity
    except (OSError, UnicodeError, json.JSONDecodeError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def add_device_identities(devices):
    with ThreadPoolExecutor(max_workers=min(32, len(devices) or 1)) as executor:
        identities = executor.map(
            request_device_identity,
            (device["ip"] for device in devices),
        )
        for device, identity in zip(devices, identities):
            device["identity"] = identity


def get_mac_details(mac):
    first_octet = int(mac.split(":")[0], 16)
    if first_octet & 0x02:
        return "Private/randomized", "Unavailable (private MAC)"

    _, vendor = MANUFDB.lookup(mac)
    if vendor == mac:
        vendor = "Unknown"
    return "Globally unique", vendor


def check_tcp_port(target):
    ip, port = target
    try:
        with socket.create_connection((ip, port), timeout=0.25):
            return ip, port
    except OSError:
        return None


def add_open_services(devices):
    targets = [
        (device["ip"], port)
        for device in devices
        for port in COMMON_TCP_SERVICES
    ]
    open_ports = {device["ip"]: [] for device in devices}

    if targets:
        with ThreadPoolExecutor(max_workers=min(64, len(targets))) as executor:
            for result in executor.map(check_tcp_port, targets):
                if result:
                    ip, port = result
                    open_ports[ip].append(port)

    for device in devices:
        device["services"] = [
            f"{COMMON_TCP_SERVICES[port]} ({port})"
            for port in sorted(open_ports[device["ip"]])
        ]


def identify_device(device, gateway_ip):
    if device["identity"]:
        return device["identity"]["type"]

    ports = {
        int(service.rsplit("(", 1)[1].rstrip(")"))
        for service in device["services"]
    }

    if device["ip"] == gateway_ip:
        return "Network gateway/router"
    if ports & {515, 631, 9100}:
        return "Likely printer"
    if 554 in ports:
        return "Likely camera or media streamer"
    if ports & {8008, 8009}:
        return "Likely Chromecast/media device"
    if 62078 in ports:
        return "Likely Apple mobile device"
    if ports & {1883, 8883}:
        return "Likely IoT/MQTT device"
    if ports & {139, 445}:
        return "Computer or network storage"
    if 32400 in ports:
        return "Plex media server"
    if ports & {80, 443, 8080, 8443}:
        return "Web-enabled device"
    if 22 in ports:
        return "SSH-enabled computer/device"
    return "Unidentified client"


def discover_devices(interface=None):
    # Scapy inspects raw network interfaces while importing these modules. Keep
    # them local so pytest can safely collect this helper without root access.
    from scapy.layers.l2 import ARP, Ether
    from scapy.sendrecv import srp

    network, interface, gateway_ip = get_network(interface)

    print(f"Auto detected network: {network} on {interface}")

    packet = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=network)

    results = srp(
        packet,
        iface=interface,
        timeout=3,
        verbose=False
    )[0]

    devices = []

    for sent, received in results:
        mac_type, vendor = get_mac_details(received.hwsrc)
        devices.append({
            "ip": received.psrc,
            "mac": received.hwsrc,
            "mac_type": mac_type,
            "vendor": vendor,
            "response_ms": round(float(received.time - sent.sent_time) * 1000, 2),
        })

    if not devices:
        print(
            "No ARP responses were received. The Wi-Fi may have client isolation "
            "enabled, or the selected interface may be wrong."
        )
        return []

    print(f"Requesting {IDENTITY_PATH} from every device...")
    add_device_identities(devices)

    print("Resolving device names...")
    with ThreadPoolExecutor(max_workers=min(32, len(devices) or 1)) as executor:
        names = executor.map(get_device_name, (device["ip"] for device in devices))
        for device, (name, name_source) in zip(devices, names):
            if device["identity"]:
                device["name"] = device["identity"]["name"]
                device["name_source"] = f"HTTP {IDENTITY_PATH}"
            else:
                device["name"] = name
                device["name_source"] = name_source

    print("Checking common services...")
    add_open_services(devices)

    for device in devices:
        device["device_type"] = identify_device(device, gateway_ip)

    devices.sort(key=lambda device: ipaddress.ip_address(device["ip"]))

    return devices


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover devices on the local IPv4 network")
    parser.add_argument(
        "-i",
        "--interface",
        help="network interface to scan, for example wlan0 or wlp2s0",
    )
    args = parser.parse_args()

    try:
        devices = discover_devices(args.interface)
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        parser.error(str(error))

    for device in devices:
        print(f"\n{device['ip']} — {device['name']}")
        print(f"  Name source: {device['name_source']}")
        print(f"  MAC: {device['mac']} ({device['mac_type']})")
        print(f"  Vendor: {device['vendor']}")
        print(f"  Likely type: {device['device_type']}")
        print(f"  ARP response: {device['response_ms']} ms")
        print(f"  Common services: {', '.join(device['services']) or 'None detected'}")

        identity = device["identity"]
        if identity:
            print(f"  Identity protocol: {identity['protocol']}")
            for label, field in (
                ("Device ID", "device_id"),
                ("Hostname", "hostname"),
                ("Model", "model"),
                ("Firmware", "firmware_version"),
                ("Reported manufacturer", "manufacturer"),
                ("Wi-Fi SSID", "ssid"),
                ("Wi-Fi RSSI", "rssi"),
                ("Uptime", "uptime_ms"),
                ("Capabilities", "capabilities"),
            ):
                if field in identity:
                    value = identity[field]
                    if isinstance(value, list):
                        value = ", ".join(str(item) for item in value)
                    if field == "rssi":
                        value = f"{value} dBm"
                    elif field == "uptime_ms":
                        value = f"{value} ms"
                    print(f"  {label}: {value}")
