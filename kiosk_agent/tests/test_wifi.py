from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from kiosk_agent.models import ChaletConfig
from kiosk_agent.wifi import WifiError, _parse_scan, connect_wifi

IN_MEMORY_CHANNELS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


SAMPLE_SCAN = "\n".join([
    "no:Digt:80:WPA2",
    "no::77:WPA2",
    "no:FinTechSys 2GHz:75:WPA1 WPA2",
    "yes:FintechSys 5GHz:56:WPA1 WPA2",
    "no:FintechSys 5GHz:40:WPA1 WPA2",
    "no:OpenNet:60:",
])


@override_settings(CHANNEL_LAYERS=IN_MEMORY_CHANNELS, KIOSK_API_KEY="")
class WifiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        ChaletConfig.load()
        self.client.get(reverse("kiosk-chat"))

    def test_parse_scan_dedupes_and_sorts(self):
        networks = _parse_scan(SAMPLE_SCAN)
        ssids = [n["ssid"] for n in networks]
        # Empty SSID skipped, weaker duplicate dropped, active first.
        self.assertEqual(ssids[0], "FintechSys 5GHz")
        self.assertEqual(ssids.count("FintechSys 5GHz"), 1)
        self.assertNotIn("", ssids)
        active = next(n for n in networks if n["ssid"] == "FintechSys 5GHz")
        self.assertTrue(active["active"])
        self.assertEqual(active["signal"], 56)
        open_net = next(n for n in networks if n["ssid"] == "OpenNet")
        self.assertFalse(open_net["secured"])

    def test_parse_scan_caps_at_max(self):
        lines = [f"no:Net{i:02d}:{i % 100}:WPA2" for i in range(40)]
        networks = _parse_scan("\n".join(lines))
        self.assertLessEqual(len(networks), 20)

    @patch("kiosk_agent.wifi._nmcli_available", return_value=True)
    @patch("kiosk_agent.wifi._saved_wifi_profiles", return_value={})
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_status_view_returns_networks(self, run, saved, available):
        run.side_effect = [SAMPLE_SCAN, "full"]
        response = self.client.get(reverse("kiosk_agent:wifi-status"))
        self.assertEqual(response.status_code, 200)
        wifi = response.json()["wifi"]
        self.assertTrue(wifi["available"])
        self.assertTrue(wifi["connected"])
        self.assertEqual(wifi["ssid"], "FintechSys 5GHz")
        self.assertIn("network", response.json())

    @patch("kiosk_agent.wifi._nmcli_available", return_value=True)
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_status_view_unavailable_hardware(self, run, available):
        run.side_effect = WifiError("unavailable", "no nmcli")
        response = self.client.get(reverse("kiosk_agent:wifi-status"))
        self.assertEqual(response.status_code, 200)
        wifi = response.json()["wifi"]
        self.assertFalse(wifi["connected"])
        self.assertEqual(wifi["networks"], [])

    @patch("kiosk_agent.wifi._nmcli_available", return_value=False)
    def test_status_view_without_nmcli_reports_unavailable(self, available):
        # Containers / servers without NetworkManager degrade gracefully.
        response = self.client.get(reverse("kiosk_agent:wifi-status"))
        self.assertEqual(response.status_code, 200)
        wifi = response.json()["wifi"]
        self.assertFalse(wifi["available"])
        self.assertFalse(wifi["connected"])
        self.assertEqual(wifi["networks"], [])

    @patch("kiosk_agent.wifi._saved_wifi_profiles", return_value={})
    @patch("kiosk_agent.wifi._add_wifi_profile")
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_connect_success(self, run, add_profile, saved):
        # device status + delete (absent) + up; profile creation + check mocked.
        run.side_effect = [
            "wlp0s20f3:wifi:connected",
            WifiError("not_found", "no such connection"),
            "",
        ]
        add_profile.return_value = "(objectpath '/org/freedesktop/NetworkManager/Settings/81',)"
        with patch("kiosk_agent.wifi.get_wifi_status") as status:
            status.return_value = {"ssid": "TargetNet"}
            result = connect_wifi("TargetNet", "correcthorsebatterystaple", "WPA2")
        self.assertTrue(result["success"])
        add_profile.assert_called_once_with(
            "TargetNet", "correcthorsebatterystaple", "wlp0s20f3", "wpa-psk")
        up_args = run.call_args_list[2][0][0]
        self.assertEqual(up_args, ["con", "up", "TargetNet"])

    @patch("kiosk_agent.wifi._saved_wifi_profiles", return_value={})
    @patch("kiosk_agent.wifi._add_wifi_profile")
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_connect_open_network_has_no_psk(self, run, add_profile, saved):
        run.side_effect = ["wlp0s20f3:wifi:disconnected", "", ""]
        with patch("kiosk_agent.wifi.get_wifi_status") as status:
            status.return_value = {"ssid": "OpenNet"}
            result = connect_wifi("OpenNet")
        self.assertTrue(result["success"])
        add_profile.assert_called_once_with("OpenNet", "", "wlp0s20f3", "wpa-psk")

    @patch("kiosk_agent.wifi._saved_wifi_profiles", return_value={})
    @patch("kiosk_agent.wifi._add_wifi_profile")
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_connect_wpa3_only_uses_sae(self, run, add_profile, saved):
        run.side_effect = ["wlp0s20f3:wifi:connected", "", ""]
        with patch("kiosk_agent.wifi.get_wifi_status") as status:
            status.return_value = {"ssid": "NewNet"}
            connect_wifi("NewNet", "correcthorsebatterystaple", "WPA3")
        add_profile.assert_called_once_with(
            "NewNet", "correcthorsebatterystaple", "wlp0s20f3", "sae")

    @patch("kiosk_agent.wifi._add_wifi_profile")
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_connect_reuses_saved_profile_without_password(self, run, add_profile):
        with patch("kiosk_agent.wifi._saved_wifi_profiles",
                   return_value={"KnownNet": "uuid-1234"}):
            with patch("kiosk_agent.wifi.get_wifi_status") as status:
                status.return_value = {"ssid": "KnownNet"}
                result = connect_wifi("KnownNet")
        self.assertTrue(result["success"])
        add_profile.assert_not_called()
        run.assert_called_once_with(["con", "up", "uuid-1234"], timeout=30)

    @patch("kiosk_agent.wifi._add_wifi_profile")
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_connect_saved_profile_with_new_password(self, run, add_profile):
        run.side_effect = ["", ""]
        with patch("kiosk_agent.wifi._saved_wifi_profiles",
                   return_value={"KnownNet": "uuid-1234"}):
            with patch("kiosk_agent.wifi.get_wifi_status") as status:
                status.return_value = {"ssid": "KnownNet"}
                result = connect_wifi("KnownNet", "newpassword123", "WPA2")
        self.assertTrue(result["success"])
        add_profile.assert_not_called()
        mod_args = run.call_args_list[0][0][0]
        self.assertEqual(mod_args[:3], ["con", "mod", "uuid-1234"])
        self.assertIn("newpassword123", mod_args)
        self.assertEqual(run.call_args_list[1][0][0], ["con", "up", "uuid-1234"])

    @patch("kiosk_agent.wifi._run_nmcli")
    def test_saved_profiles_handles_colons_in_name(self, run):
        run.side_effect = [
            "My Cafe:uuid-1:802-11-wireless\neth0:uuid-2:802-11-ethernet",
            "802-11-wireless.ssid:Cafe:Guest",
        ]
        from kiosk_agent.wifi import _saved_wifi_profiles
        self.assertEqual(
            _saved_wifi_profiles(only={"Cafe:Guest"}), {"Cafe:Guest": "uuid-1"})

    @patch("kiosk_agent.wifi._nmcli_available", return_value=True)
    @patch("kiosk_agent.wifi._saved_wifi_profiles", return_value={"HomeNet": "uuid-9"})
    @patch("kiosk_agent.wifi._run_nmcli")
    def test_status_marks_saved_networks(self, run, saved, available):
        run.side_effect = ["yes:HomeNet:80:WPA2\nno:OtherNet:60:WPA2", "full"]
        response = self.client.get(reverse("kiosk_agent:wifi-status"))
        self.assertEqual(response.status_code, 200)
        networks = {n["ssid"]: n for n in response.json()["wifi"]["networks"]}
        self.assertTrue(networks["HomeNet"]["saved"])
        self.assertFalse(networks["OtherNet"]["saved"])

    def test_add_wifi_profile_builds_minimal_payload(self):
        from kiosk_agent import wifi as wifi_module
        from types import SimpleNamespace
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return SimpleNamespace(returncode=0,
                                   stdout="(objectpath '/org/freedesktop/NetworkManager/Settings/81',)",
                                   stderr="")

        with patch.object(wifi_module.subprocess, "run", side_effect=fake_run), \
             patch.object(wifi_module.shutil, "which", return_value="/usr/bin/gdbus"):
            wifi_module._add_wifi_profile("001", "s3cret'\\pw", "wlp0s20f3", "wpa-psk")
        argv = captured["argv"]
        self.assertEqual(argv[:3], ["gdbus", "call", "--system"])
        payload = argv[-1]
        # Minimal 1.46-compatible set only — never the 1.52-only property.
        self.assertNotIn("denylist", payload)
        self.assertNotIn("blacklist", payload)
        self.assertIn("'key-mgmt': <'wpa-psk'>", payload)
        # SSID as GVariant bytes, quote/backslash escaping intact.
        self.assertIn("[byte 0x30, byte 0x30, byte 0x31]", payload)
        self.assertIn("s3cret\\'\\\\pw", payload)

    def test_add_wifi_profile_maps_auth_errors(self):
        from kiosk_agent import wifi as wifi_module
        from types import SimpleNamespace
        failure = SimpleNamespace(
            returncode=1, stdout="",
            stderr="GDBus.Error:org.freedesktop.DBus.Error.AccessDenied: NotAuthorized")
        with patch.object(wifi_module.subprocess, "run", return_value=failure), \
             patch.object(wifi_module.shutil, "which", return_value="/usr/bin/gdbus"):
            with self.assertRaises(WifiError) as ctx:
                wifi_module._add_wifi_profile("Net", "password123", "wlp0s20f3", "wpa-psk")
        self.assertEqual(ctx.exception.code, "auth_failed")

    def test_add_wifi_profile_without_gdbus(self):
        from kiosk_agent import wifi as wifi_module
        with patch.object(wifi_module.shutil, "which", return_value=None):
            with self.assertRaises(WifiError) as ctx:
                wifi_module._add_wifi_profile("Net", "password123", "wlp0s20f3", "wpa-psk")
        self.assertEqual(ctx.exception.code, "unavailable")

    @patch("kiosk_agent.wifi._run_nmcli")
    def test_connect_without_adapter(self, run):
        run.return_value = "eth0:ethernet:connected"
        with self.assertRaises(WifiError) as ctx:
            connect_wifi("SomeNet", "correcthorsebatterystaple")
        self.assertEqual(ctx.exception.code, "unavailable")

    def test_connect_rejects_short_password(self):
        with self.assertRaises(WifiError) as ctx:
            connect_wifi("SomeNet", "short")
        self.assertEqual(ctx.exception.code, "invalid_password")

    def test_connect_rejects_blank_ssid(self):
        with self.assertRaises(WifiError) as ctx:
            connect_wifi("   ", "")
        self.assertEqual(ctx.exception.code, "invalid_ssid")

    @patch("kiosk_agent.wifi.connect_wifi")
    def test_connect_view_success(self, connect):
        connect.return_value = {"success": True, "ssid": "TargetNet"}
        response = self.client.post(
            reverse("kiosk_agent:wifi-connect"),
            {"ssid": "TargetNet", "password": "correcthorsebatterystaple"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_connect_view_rejects_short_password(self):
        response = self.client.post(
            reverse("kiosk_agent:wifi-connect"),
            {"ssid": "TargetNet", "password": "short"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("kiosk_agent.wifi.connect_wifi")
    def test_connect_view_maps_auth_failure(self, connect):
        connect.side_effect = WifiError("auth_failed", "Wrong password for this network.")
        response = self.client.post(
            reverse("kiosk_agent:wifi-connect"),
            {"ssid": "TargetNet", "password": "wrongpassword1"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Wrong password", response.json()["detail"])

    def test_wifi_endpoints_require_kiosk_access(self):
        anon = APIClient()
        self.assertEqual(anon.get(reverse("kiosk_agent:wifi-status")).status_code, 403)
        self.assertEqual(
            anon.post(reverse("kiosk_agent:wifi-connect"), {"ssid": "x"}, format="json").status_code,
            403,
        )
