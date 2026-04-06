#!/usr/bin/env python3
"""
Multi-method WiFi device scanner.
Combines ARP, ping sweep, and nmap for best coverage.
"""

import socket
import subprocess
import ipaddress
import requests
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try importing scapy
try:
    from scapy.all import ARP, Ether, srp, conf
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

def get_local_ip_and_subnet():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    subnet = ip.rsplit('.', 1)[0] + ".0/24"
    return ip, subnet

def get_vendor(mac):
    try:
        url = f"https://api.macvendors.com/{mac}"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return "Unknown"

def get_hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except:
        return ""

def ping_host(ip):
    """Ping a single IP. Returns IP if alive, else None."""
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "1", str(ip)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return str(ip) if result.returncode == 0 else None

def ping_sweep(subnet):
    """Ping every host in the subnet in parallel."""
    print("  [1/3] Running ping sweep (wakes up sleeping devices)...")
    network = ipaddress.ip_network(subnet, strict=False)
    alive = set()
    hosts = list(network.hosts())
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(ping_host, ip): ip for ip in hosts}
        for future in as_completed(futures):
            result = future.result()
            if result:
                alive.add(result)
    print(f"      → Found {len(alive)} host(s) responding to ping")
    return alive

def arp_scan(subnet):
    """ARP scan using scapy."""
    print("  [2/3] Running ARP scan...")
    if not SCAPY_AVAILABLE:
        print("      → Scapy not available, skipping")
        return {}
    
    conf.verb = 0
    packet = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet)
    answered, _ = srp(packet, timeout=3, verbose=False, retry=2)
    
    results = {}
    for sent, received in answered:
        results[received.psrc] = received.hwsrc
    print(f"      → Found {len(results)} host(s) via ARP")
    return results

def read_arp_table():
    """Read the kernel ARP cache using 'ip neigh' (modern Linux)."""
    print("  [3/3] Reading ARP cache...")
    mac_map = {}
    try:
        output = subprocess.check_output(["ip", "neigh"], text=True)
        for line in output.splitlines():
            parts = line.split()
            # Format: <IP> dev <iface> lladdr <MAC> <STATE>
            if "lladdr" in parts:
                ip  = parts[0]
                mac = parts[parts.index("lladdr") + 1]
                if "FAILED" not in line and "INCOMPLETE" not in line:
                    mac_map[ip] = mac
    except Exception as e:
        print(f"      → Could not read ARP table: {e}")
    print(f"      → {len(mac_map)} entr(ies) in ARP cache")
    return mac_map

def is_randomized_mac(mac):
    """
    Phones randomize their MAC. The 2nd-least-significant bit of the first octet
    being set (locally administered) is the giveaway.
    e.g. 22:... 12:... A2:... — first octet is even but bit 1 is set.
    """
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0x02)  # locally administered bit
    except:
        return False

def guess_device_type(mac, hostname, vendor):
    """Make a best-guess at device type from available clues."""
    if is_randomized_mac(mac):
        return "📱 Phone/Tablet (randomized MAC — privacy mode)"
    h = (hostname + vendor).lower()
    if any(x in h for x in ["iphone", "apple", "ipad"]):
        return "🍎 Apple device"
    if any(x in h for x in ["android", "samsung", "xiaomi", "huawei", "oppo", "oneplus"]):
        return "📱 Android device"
    if any(x in h for x in ["router", "gateway", "dlink", "tp-link", "tplink", "asus", "netgear", "huawei", "zte", "technicolor"]):
        return "📡 Router/Gateway"
    if any(x in h for x in ["windows", "desktop", "laptop", "intel", "realtek"]):
        return "💻 PC/Laptop"
    if any(x in h for x in ["ubuntu", "linux", "debian", "arch", "raspi", "raspberry"]):
        return "🐧 Linux device"
    if any(x in h for x in ["smart", "tv", "cast", "roku", "fire", "echo", "alexa", "nest", "ring"]):
        return "📺 Smart TV/IoT"
    if vendor and vendor != "Unknown":
        return f"🔌 {vendor}"
    return "❓ Unknown"

def format_mac(mac):
    """Normalise to upper-case colon-separated."""
    return mac.replace("-", ":").upper()

def scan(subnet):
    print(f"\nScanning {subnet}  (this may take ~15 seconds)\n")

    # Step 1: ping sweep — forces devices to appear in ARP table
    ping_sweep(subnet)

    # Step 2: ARP scan via scapy
    arp_direct = arp_scan(subnet)

    # Step 3: Read kernel ARP cache (populated by ping sweep)
    arp_cache = read_arp_table()

    # Merge all sources
    all_ips = set(arp_direct.keys()) | set(arp_cache.keys())

    devices = []
    for ip in sorted(all_ips, key=lambda x: list(map(int, x.split('.')))):
        mac = arp_direct.get(ip) or arp_cache.get(ip) or "??:??:??:??:??:??"
        mac = format_mac(mac)
        devices.append({"ip": ip, "mac": mac})

    return devices

def enrich(devices, my_ip):
    print(f"\nEnriching {len(devices)} device(s) (hostname + vendor)...\n")
    enriched = []
    for d in devices:
        hostname = get_hostname(d["ip"])
        vendor   = get_vendor(d["mac"]) if not is_randomized_mac(d["mac"]) else "N/A (randomized)"
        dtype    = guess_device_type(d["mac"], hostname, vendor)
        label    = "  ← THIS MACHINE" if d["ip"] == my_ip else ""
        enriched.append({**d, "hostname": hostname, "vendor": vendor, "type": dtype, "label": label})
    return enriched

def print_table(devices):
    print("\n" + "═" * 90)
    print(f"  {'IP':<16} {'MAC':<20} {'HOSTNAME':<22} DEVICE TYPE")
    print("═" * 90)
    for d in devices:
        hostname = (d["hostname"] or "-")[:21]
        print(f"  {d['ip']:<16} {d['mac']:<20} {hostname:<22} {d['type']}{d['label']}")
    print("═" * 90)
    print(f"  Total: {len(devices)} device(s) found")
    rand = sum(1 for d in devices if is_randomized_mac(d["mac"]))
    if rand:
        print(f"  ℹ  {rand} device(s) use randomized MACs (modern phones/tablets) — vendor lookup not possible")
    print()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠  Run with sudo for best results: sudo -E ./venv/bin/python scan_wifi.py")
        sys.exit(1)

    my_ip, subnet = get_local_ip_and_subnet()
    devices = scan(subnet)

    if not devices:
        print("\nNo devices found. Try running with sudo.")
        sys.exit(0)

    enriched = enrich(devices, my_ip)
    print_table(enriched)