# VPN Tunneling — Phone 4G Capture via strongSwan IKEv2

## Topology

```
Phone(4G / any network)
  │ IKEv2 IPSec tunnel (system VPN, no app)
  ▼
Cloud VM / Soft Router
  ├─ strongSwan (IKEv2 server)
  ├─ extractor (tcpdump -i any, BPF filter: port 7777)
  └─ relay (FastAPI :8000)
  │
  ▼
Game Server 47.96.0.227:7777
```

**Full tunnel** (`leftsubnet=0.0.0.0/0`): ALL phone traffic routes through the VPN.
Android's built-in VPN client rejects a narrowed traffic selector and tears down the
tunnel right after IKE_AUTH, so server-side split tunnel is **not** possible without the
strongSwan app. Trade-off: WeChat/browser also traverse the cloud server while VPN is on.

## Why This Works

- Phone's native game client does ALL auth/encryption itself (native .so)
- strongSwan only tunnels IP packets — doesn't touch app data
- extractor passively sniffs decrypted TCP traffic on the VPN host
- `0x2BC0` game data frames are unencrypted at TCP layer (already verified)

## Phone Setup (1 minute, one time only)

**Zero app install** — uses Android's built-in system VPN.
**Pure PSK**: only 3 fields, no username/password, no certificate.

1. Settings > Network & internet > VPN
2. Tap "+" (Add VPN)
3. Fill in EXACTLY these 3 fields:
   - **Type: `IKEv2/IPSec PSK`** — MUST be PSK. NOT RSA (certificate),
     NOT MSCHAPv2. Wrong type = stuck on "connecting / not secure".
   - Server: `<server_public_ip>`
   - Pre-shared key: `<psk>`
   - IPSec identifier: **leave empty**
   - Username / Password: **do not fill**
4. Save → tap gear icon → Enable "Always-on VPN"
5. Done. VPN auto-connects on 4G/WiFi/any network forever.

> If you previously created an entry with Type RSA / certificate, delete it
> first, then add a fresh PSK entry as above.

## Server Deploy (3 minutes)

### Prerequisites
- Linux server (Ubuntu/Debian 20.04+, OpenWRT, Alpine)
- Public IP (cloud VM, VPS, or DDNS)
- UDP ports 500 and 4500 open in firewall

### Step 1: Install strongSwan
```bash
sudo bash install_vpn.sh
```

### Step 2: Generate configs
```bash
python vpn_configure.py --server-ip <your_public_ip>
```
This creates:
- `ipsec.conf` — server config (pure PSK: `leftauth=psk` / `rightauth=psk`)
- `ipsec.secrets` — single `: PSK "..."` line
- `phone-setup.txt` — phone setup guide (the 3 fields to fill in)

### Step 3: Deploy configs
```bash
sudo cp ipsec.conf /etc/ipsec.conf
sudo cp ipsec.secrets /etc/ipsec.secrets
sudo chmod 600 /etc/ipsec.secrets
sudo ipsec restart
sudo ipsec status  # verify: should show "mahjong-vpn" connection loaded
```

> The pure-PSK system VPN only needs the 3 fields above typed once on the
> phone. No captive portal / `portal.py` / soft-router config push is needed.

### Step 4: Start extractor + relay
```bash
python run.py  # extractor with config pointing to relay
```
extractor captures on `any` interface with BPF filter `port 7777`.
Decrypted VPN traffic = visible to tcpdump.

## Verify
1. Phone: VPN connected (key icon in status bar)
2. Open game, play a round
3. Browser: `http://<relay_url>:8000/?token=<api_token>`
4. Should see real-time hand tiles

## Troubleshooting

| Problem | Check |
|---------|-------|
| VPN won't connect ("connecting / not secure") | **Phone Type MUST be `IKEv2/IPSec PSK`.** Choosing RSA/certificate or MSCHAPv2 hangs on "connecting…not secure" and never connects. Delete the wrong entry and re-add as PSK. |
| | `ipsec status` — connection should be "loaded" |
| | Is UDP 4500 open? `nc -u <server_ip> 4500` |
| | `ipsec.secrets` must be a single `: PSK "..."` line; PSK on phone must match it exactly |
| No data | `tcpdump -i any port 7777` — should see traffic |
| | Is extractor configured with correct relay_url? |
| Server behind NAT | Set `leftid=<public_ip>` in ipsec.conf and forward UDP 500,4500 |
