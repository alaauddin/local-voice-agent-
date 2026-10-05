from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from kiosk_agent.device_discovery import _local_scan_network


@override_settings(DEVICE_DISCOVERY_NETWORK="")
class DeviceDiscoveryNetworkTests(SimpleTestCase):
    def test_physical_lan_wins_when_docker_is_default_interface(self):
        fake_netifaces = SimpleNamespace(
            AF_INET=2,
            gateways=lambda: {"default": {2: ("172.17.0.1", "docker0")}},
            interfaces=lambda: ["docker0", "wlp0s20f3"],
            ifaddresses=lambda interface: {
                2: [
                    {
                        "addr": "172.17.0.1" if interface == "docker0" else "192.168.1.5",
                        "netmask": "255.255.255.0",
                    }
                ]
            },
        )

        with patch.dict("sys.modules", {"netifaces": fake_netifaces}):
            network, local_ip, interface = _local_scan_network()

        self.assertEqual(str(network), "192.168.1.0/24")
        self.assertEqual(str(local_ip), "192.168.1.5")
        self.assertEqual(interface, "wlp0s20f3")
