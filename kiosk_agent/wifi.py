"""Wi-Fi control for the on-site kiosk box (NetworkManager via nmcli).

All functions are best-effort and never raise for expected system states —
they return structured dicts with "" / False fallbacks so the kiosk UI can
always render. Only unexpected programming errors propagate.

Security note: never log the PSK. Validation rejects over-long inputs.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

NMCLI = "nmcli"
SCAN_TIMEOUT = 12
CONNECT_TIMEOUT = 30
MAX_NETWORKS = 20
# D-Bus system bus inside the container. docker-compose mounts the host's
# /run/dbus here so nmcli drives the *host* NetworkManager, not the container.
SYSTEM_BUS_ADDRESS = "unix:path=/run/dbus/system_bus_socket"


class WifiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _nmcli_available():
    return bool(shutil.which(NMCLI))


def _run_nmcli(args, timeout):
    """Run nmcli, returning stdout stripped. Raises WifiError on failure."""
    if not _nmcli_available():
        raise WifiError("unavailable", "Wi-Fi control is not available on this device.")
    env = dict(os.environ)
    # Talk to the host NetworkManager via the mounted D-Bus socket.
    env.setdefault("DBUS_SYSTEM_BUS_ADDRESS", SYSTEM_BUS_ADDRESS)
    try:
        result = subprocess.run(
            [NMCLI, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise WifiError("timeout", "The Wi-Fi operation timed out.")
    except OSError:
        raise WifiError("unavailable", "Wi-Fi control is not available on this device.")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip().lower()
        if "no network with ssid" in stderr or "network not found" in stderr:
            raise WifiError("not_found", "This network was not found. Rescan and try again.")
        if "secrets were required" in stderr or "password" in stderr or "psk" in stderr:
            raise WifiError("auth_failed", "Wrong password for this network.")
        if "already active" in stderr or "already connected" in stderr:
            return (result.stdout or "").strip()
        raise WifiError(
            "controller_error",
            (result.stderr or "").strip()[:200] or "Could not change the Wi-Fi network.",
        )
    return (result.stdout or "").strip()


def _parse_scan(output):
    """Parse `nmcli -t -f ACTIVE,SSID,SIGNAL,SECURITY dev wifi` output.

    Dedupes by SSID keeping the strongest signal, active network first,
    then sorts by signal desc. Skips empty/hidden SSIDs.
    """
    best = {}
    order = []
    for line in (output or "").splitlines():
        parts = line.split(":", 3)
        if len(parts) < 2:
            continue
        active = parts[0].strip().lower() == "yes"
        ssid = (parts[1] if len(parts) > 1 else "").strip()
        try:
            signal = int((parts[2] if len(parts) > 2 else "").strip() or 0)
        except ValueError:
            signal = 0
        security = (parts[3] if len(parts) > 3 else "").strip()
        if not ssid or len(ssid) > 64:
            continue
        signal = max(0, min(100, signal))
        secured = security not in ("", "--", "none", "open")
        entry = {"ssid": ssid, "signal": signal, "security": security,
                 "secured": secured, "active": active}
        prev = best.get(ssid)
        if prev is None:
            best[ssid] = entry
            order.append(ssid)
        elif active and not prev["active"]:
            best[ssid] = entry
        elif active == prev["active"] and signal > prev["signal"]:
            best[ssid] = entry
    networks = [best[ssid] for ssid in order]
    networks.sort(key=lambda n: (not n["active"], -n["signal"]))
    return networks[:MAX_NETWORKS]


def _saved_wifi_profiles(only=None):
    """Map SSID -> connection UUID for saved Wi-Fi profiles. Never raises.

    With ``only`` (a set of SSIDs), per-profile lookups are limited to
    resolving just those — a full dump is slow on hosts with many profiles.
    """
    try:
        out = _run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "con", "show"], timeout=10)
    except WifiError:
        return {}
    candidates = []
    for line in (out or "").splitlines():
        # The profile NAME may itself contain ':' — split from the right.
        parts = line.rsplit(":", 2)
        if len(parts) != 3:
            continue
        name, uuid, conn_type = parts
        if conn_type == "802-11-wireless" and uuid:
            candidates.append((name, uuid))
    wanted = set(only) if only is not None else None
    profiles = {}
    # Fast path: NetworkManager names new profiles after the SSID.
    for name, uuid in candidates:
        if wanted is None or name in wanted:
            profiles.setdefault(name, uuid)
    if wanted is not None and wanted <= set(profiles):
        return {ssid: profiles[ssid] for ssid in wanted if ssid in profiles}
    # Slow path: read the stored SSID (profiles can be renamed).
    for name, uuid in candidates:
        if uuid in set(profiles.values()):
            continue
        try:
            raw = _run_nmcli(
                ["-t", "-f", "802-11-wireless.ssid", "con", "show", uuid],
                timeout=5,
            ).strip()
        except WifiError:
            continue
        # Terse output prefixes the field name: "802-11-wireless.ssid:<ssid>".
        _, _, ssid = raw.partition(":")
        ssid = ssid.strip() or name
        if wanted is None or ssid in wanted:
            profiles.setdefault(ssid, uuid)
        if wanted is not None and wanted <= set(profiles):
            break
    if wanted is not None:
        return {ssid: profiles[ssid] for ssid in wanted if ssid in profiles}
    return profiles


def get_wifi_status(rescan=False):
    """Return current connection + visible networks. Never raises WifiError."""
    if not _nmcli_available():
        return {"available": False, "connected": False, "ssid": "",
                "signal": 0, "security": "", "connectivity": "",
                "networks": []}
    if rescan:
        try:
            _run_nmcli(["dev", "wifi", "rescan"], timeout=SCAN_TIMEOUT)
        except WifiError as exc:
            logger.debug("Wi-Fi rescan failed: %s", exc.code)
    try:
        scan_out = _run_nmcli(
            ["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "no" if not rescan else "yes"],
            timeout=SCAN_TIMEOUT,
        )
    except WifiError:
        try:
            scan_out = _run_nmcli(
                ["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi"],
                timeout=SCAN_TIMEOUT,
            )
        except WifiError as exc:
            logger.debug("Wi-Fi scan failed: %s", exc.code)
            return {"available": True, "connected": False, "ssid": "",
                    "signal": 0, "security": "", "connectivity": "",
                    "networks": []}
    networks = _parse_scan(scan_out)
    active = next((n for n in networks if n["active"]), None)
    saved = _saved_wifi_profiles(only={n["ssid"] for n in networks})
    for network in networks:
        network["saved"] = network["ssid"] in saved
    try:
        connectivity = _run_nmcli(["networking", "connectivity"], timeout=5).strip().lower()
    except WifiError:
        connectivity = ""
    return {
        "available": True,
        "connected": bool(active),
        "ssid": active["ssid"] if active else "",
        "signal": active["signal"] if active else 0,
        "security": active["security"] if active else "",
        "connectivity": connectivity,
        "networks": networks,
    }


def _wifi_ifname():
    """Name of the host Wi-Fi adapter (e.g. wlp0s20f3). Raises WifiError."""
    try:
        out = _run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE", "device", "status"], timeout=5)
    except WifiError:
        raise WifiError("unavailable", "Could not reach NetworkManager on this device.")
    fallback = ""
    for line in (out or "").splitlines():
        parts = line.split(":")
        if len(parts) < 3 or parts[1] != "wifi" or not parts[0]:
            continue
        if parts[2] == "connected":
            return parts[0]
        fallback = fallback or parts[0]
    if fallback:
        return fallback
    raise WifiError("unavailable", "No Wi-Fi adapter was found on this device.")


def _gdbus_available():
    return bool(shutil.which("gdbus"))


def _gvariant_str(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _add_wifi_profile(ssid, password, iface, key_mgmt):
    """Create a system Wi-Fi profile via NetworkManager D-Bus directly.

    ``nmcli con add`` (v1.52) injects ``mac-address-denylist``, which older
    daemons (e.g. host NM 1.46) reject with "unknown property". Sending only
    the minimal property set over D-Bus works on both. Never logs the PSK.
    """
    import uuid as uuidlib

    if not _gdbus_available():
        raise WifiError("unavailable", "Wi-Fi control is not available on this device.")
    ssid_bytes = ", ".join("byte 0x%02x" % b for b in ssid.encode("utf-8"))
    wireless_sec = ""
    if password:
        wireless_sec = (
            "'802-11-wireless-security': {'key-mgmt': <%s>, 'psk': <%s>}, "
            % (_gvariant_str(key_mgmt), _gvariant_str(password))
        )
    payload = (
        "{'connection': {'id': <%s>, 'uuid': <%s>, 'type': <'802-11-wireless'>, "
        "'interface-name': <%s>}, "
        "'802-11-wireless': {'ssid': <[%s]>, 'mode': <'infrastructure'>}, %s"
        "'ipv4': {'method': <'auto'>}, 'ipv6': {'method': <'auto'>}}"
        % (
            _gvariant_str(ssid),
            _gvariant_str(str(uuidlib.uuid4())),
            _gvariant_str(iface),
            ssid_bytes,
            wireless_sec,
        )
    )
    env = dict(os.environ)
    env.setdefault("DBUS_SYSTEM_BUS_ADDRESS", SYSTEM_BUS_ADDRESS)
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--system",
                "--dest", "org.freedesktop.NetworkManager",
                "--object-path", "/org/freedesktop/NetworkManager/Settings",
                "--method", "org.freedesktop.NetworkManager.Settings.AddConnection",
                payload,
            ],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except subprocess.TimeoutExpired:
        raise WifiError("timeout", "The Wi-Fi operation timed out.")
    except OSError:
        raise WifiError("unavailable", "Wi-Fi control is not available on this device.")
    out = (result.stdout or "").strip()
    if result.returncode != 0 or "objectpath" not in out:
        err = (result.stderr or "").strip()[:200]
        lowered = err.lower()
        if "notauthorized" in lowered or "accessdenied" in lowered or "not authorized" in lowered:
            raise WifiError("auth_failed", "Not allowed to change Wi-Fi on this device.")
        raise WifiError("controller_error", err or "Could not create the Wi-Fi profile.")
    return out


def connect_wifi(ssid, password="", security=""):
    """Connect to an SSID. Raises WifiError; never logs the password.

    Profile creation goes over D-Bus with a minimal property set: newer nmcli
    versions inject ``mac-address-denylist``, which older host NetworkManager
    daemons reject with "unknown property". Activation still uses nmcli.
    """
    ssid = (ssid or "").strip()
    password = password or ""
    if not ssid or len(ssid) > 64:
        raise WifiError("invalid_ssid", "Choose a valid network name.")
    if len(password) > 128:
        raise WifiError("invalid_password", "The password is too long.")
    if password and len(password) < 8:
        raise WifiError("invalid_password", "The password must be at least 8 characters.")
    # WPA3-only networks need SAE; everything else uses WPA-PSK
    # (covers WPA/WPA2 personal and transition mode).
    sec = (security or "").upper()
    key_mgmt = "sae" if ("WPA3" in sec and "WPA2" not in sec) else "wpa-psk"
    logger.info("Wi-Fi connect requested to SSID (len=%d)", len(ssid))
    saved_uuid = _saved_wifi_profiles(only={ssid}).get(ssid)
    if saved_uuid:
        # Reuse the stored profile. A newly typed password replaces the
        # stored one; otherwise the stored password is used as-is.
        if password:
            try:
                _run_nmcli(
                    ["con", "mod", saved_uuid,
                     "wifi-sec.key-mgmt", key_mgmt, "wifi-sec.psk", password],
                    timeout=10,
                )
            except WifiError as exc:
                if exc.code in ("auth_failed", "invalid_password"):
                    raise
                raise WifiError("connect_failed", exc.message)
        try:
            _run_nmcli(["con", "up", saved_uuid], timeout=CONNECT_TIMEOUT)
        except WifiError as exc:
            if exc.code in ("auth_failed", "not_found", "timeout"):
                raise
            raise WifiError("connect_failed", exc.message)
    else:
        iface = _wifi_ifname()
        # Replace any stale profile with the same name (ignore when absent).
        try:
            _run_nmcli(["con", "delete", ssid], timeout=10)
        except WifiError:
            pass
        try:
            _add_wifi_profile(ssid, password, iface, key_mgmt)
        except WifiError as exc:
            if exc.code in ("auth_failed", "invalid_ssid", "invalid_password"):
                raise
            raise WifiError("connect_failed", exc.message)
        try:
            _run_nmcli(["con", "up", ssid], timeout=CONNECT_TIMEOUT)
        except WifiError as exc:
            if exc.code in ("auth_failed", "not_found", "timeout"):
                raise
            raise WifiError("connect_failed", exc.message)
    # Verify we actually joined.
    status = get_wifi_status(rescan=False)
    if status.get("ssid") == ssid:
        return {"success": True, "ssid": ssid}
    # One more check after a short wait — NM can take a moment to report.
    import time
    time.sleep(2)
    status = get_wifi_status(rescan=False)
    if status.get("ssid") == ssid:
        return {"success": True, "ssid": ssid}
    raise WifiError("connect_failed", "Could not join this network. Check the password and try again.")
