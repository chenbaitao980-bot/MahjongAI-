# Research: Tailscale / Headscale Exit Node for Zero-Touch Passive Sniffing

- **Query**: Can a Tailscale/Headscale "exit node" on the Aliyun ECS make an Android phone route ALL traffic through that node so the node can passively tcpdump the phone's game (7777) traffic — after a one-time setup, roaming on any access network?
- **Scope**: external (web/docs/GitHub)
- **Date**: 2026-06-11

## TL;DR (the load-bearing answer)

**Yes — this is exactly what an exit node does, and the exit-node host CAN passively tcpdump the phone's 7777 traffic in cleartext.** When the Android phone selects the ECS as its exit node, Tailscale installs default routes `0.0.0.0/0, ::/0` on the phone, so 100% of the phone's egress is WireGuard-encrypted to the ECS, **decrypted there**, then NAT/forwarded out the ECS's normal internet interface to `47.96.0.227:7777`. The decrypted application packets transit the ECS's IP stack, so `tcpdump` on the ECS (on the physical NIC `eth0` or on the `tailscale0` interface) sees the phone↔game flow as ordinary cleartext TCP. This is functionally identical to the current strongSwan full-tunnel setup, but with far lower first-time friction.

The one caveat that matters for THIS use case: the game traffic must itself be unencrypted/parseable at the application layer (which the existing strongSwan sniffer already proves — Tailscale changes the *transport to the cloud*, not the *application payload*). Tailscale does NOT add or remove any TLS the app uses; whatever you can sniff today over strongSwan, you can sniff identically over a Tailscale exit node.

## Findings

### Q1 — Does an exit node route 100% of egress, and is traffic decrypted at the exit node? (YES)

From the official Tailscale docs (https://tailscale.com/kb/1103/exit-nodes, "Last validated: Dec 15, 2025"):

- > "You can route all your public internet traffic by setting a device on your network as an exit node... When you route all traffic through an exit node, you're effectively using **default routes (`0.0.0.0/0`, `::/0`)**, similar to how you would if you were using a typical VPN."
- > "**Exit nodes secure all traffic, including traffic to internet sites and applications.**"
- > "By default, exit nodes **capture all your network traffic** that isn't already directed to a subnet router or app connector."
- > Benefit "Increase visibility: **Destination logging provides increased visibility of traffic across the tailnet** and forensic analysis during security incidents." — Tailscale itself markets the exit node as a traffic-visibility/inspection chokepoint.

**Packet-level mechanics (how WireGuard/Tailscale forwarding works):**
1. Phone's OS routing table points `0.0.0.0/0` at the `tailscale0` (WireGuard) interface.
2. Phone encrypts each outbound packet (incl. its TCP SYN to `47.96.0.227:7777`) inside a WireGuard UDP datagram addressed to the ECS (direct or via a DERP relay if NAT blocks direct).
3. ECS's Tailscale daemon (`tailscaled`) **decrypts** the WireGuard payload back into the original IP packet. At this instant the cleartext packet exists in the ECS kernel/userspace netstack.
4. ECS has `net.ipv4.ip_forward=1` and an iptables/nftables **MASQUERADE (SNAT)** rule on egress, so the decrypted packet is source-NATed to the ECS's public IP and sent out `eth0` to the game server. Return packets reverse the path (DNAT back to the phone's Tailscale IP, re-encrypted, sent to phone).
5. Because step 3–4 puts the **decrypted** packet on the ECS's forwarding path, `tcpdump -i any host 47.96.0.227 and port 7777` on the ECS captures the full cleartext flow. You can capture on `tailscale0` (post-decrypt, pre-NAT — shows phone's Tailscale IP as source) or on `eth0` (post-NAT — shows ECS IP as source). For reading the hand, capture on `tailscale0` or use `host <phone-tailscale-ip> and port 7777`.

This is the same trust model as the current strongSwan PSK tunnel: the VPN terminates on the box you control, and everything past the tunnel endpoint is in the clear to that box.

### Q2 — One-time setup friction on Android + roam-forever behaviour

Setup steps (one-time):
1. Install "Tailscale" from Play Store (or sideload APK). (1 tap to install)
2. Open app, **log in**. With Headscale (Q3) you log in by entering your control-server URL + a **pre-auth key**, avoiding any Google/GitHub SaaS login. With Tailscale SaaS it's an OAuth tap (Google/GitHub/Microsoft).
3. In the app, open the menu → **"Use exit node"** → select the ECS. (2–3 taps)
4. (Optional but recommended for "block if VPN down") Android **Settings → Network & internet → VPN → Tailscale (gear) → enable "Always-on VPN" and "Block connections without VPN."** (~4 taps, one time)

Total: roughly **8–12 taps, once.** After that:
- **Survives network changes:** Tailscale/WireGuard is connectionless (UDP) and roams seamlessly across cellular ↔ any WiFi without user action; the exit-node selection is sticky and persists. This is the core advantage over re-typing IKEv2 server/PSK.
- **Survives reboot:** With Android "Always-on VPN" enabled, Tailscale auto-starts and reconnects on boot; the exit node stays selected. Source: Tailscale exit-node docs note exit-node selection persists and is enforceable; Android always-on VPN is a stock OS feature (Settings → VPN → gear).
- **No MDM/Device Owner needed** for the manual path above. (MDM/system-policy "mandatory exit node" exists but is optional and not available to you — not required.)

Net: this directly removes the user's pain point (re-entering type/server/PSK). "Connect once, roam forever" is accurate for Tailscale with always-on enabled.

### Q3 — Headscale self-hosted control plane on the same ECS (feasible, removes SaaS/login friction)

- **Repo:** `juanfont/headscale` — ★~39,900 — "An open source, self-hosted implementation of the Tailscale control server." (https://github.com/juanfont/headscale)
- Headscale is the coordination/control server only; the **data plane is still the standard Tailscale client + WireGuard**. The official Tailscale Android/desktop clients connect to Headscale by setting a custom control URL.
- **Exit nodes are fully supported by Headscale.** From https://headscale.net/stable/ref/routes/ : "Headscale supports route advertising and can be used to manage subnet routers **and exit nodes** for a tailnet... **Exit nodes can be used to route all Internet traffic for another Tailscale node.** Use it to securely access the Internet on an untrusted Wi-Fi." Docs cover: "Setup an exit node → Configure a node as exit node → Enable the exit node on the control server → Use the exit node → Automatically approve an exit node with auto approvers."
- **Pre-auth keys remove login friction:** Headscale issues pre-auth keys (`headscale preauthkeys create --user <u> --reusable --expiration 99y` style). On the phone you point the Tailscale app at `https://<ecs-domain>` and paste the key — **no Google/GitHub/SaaS account, no per-user interactive login.** Exit-node advertisement can be auto-approved server-side so no manual approval each time.
- **Co-locating on the ECS:** Headscale runs as a single Go binary (commonly via systemd or Docker). It needs a public HTTPS endpoint (port 443 + a domain/cert, or behind a reverse proxy) for the control channel; WireGuard data still flows phone↔ECS directly. Running Headscale + the exit-node Tailscale client + your sniffer all on one ECS is a common, supported topology. Web UIs exist if wanted: `gurucomputing/headscale-ui` (★~2,600), `tale/headplane` (★~2,560), `GoodiesHQ/headscale-admin` (★~1,080).
- DERP: for direct phone↔ECS connectivity you generally don't need Tailscale's DERP relays since the ECS has a public IP (the phone can reach it directly over UDP); Headscale ships an embedded DERP if a relay fallback is ever needed.

### Q4 — Compare to plain WireGuard for passive sniffing at the cloud

| Aspect | Plain WireGuard | Tailscale / Headscale exit node |
|---|---|---|
| Decryption point | Phone↔ECS hop encrypted; **decrypted at ECS**, then forwarded | Identical — phone↔ECS hop is the only encrypted hop; **decrypted at ECS** then NAT-forwarded |
| Can ECS tcpdump app (7777) traffic? | Yes (capture on `wg0`/`eth0`) | **Yes** (capture on `tailscale0`/`eth0`) — same |
| Full-tunnel config | Set `AllowedIPs = 0.0.0.0/0, ::/0` on phone peer + `MASQUERADE` + `ip_forward` on ECS | Built-in "exit node" toggle = same `0.0.0.0/0` default route, auto-managed |
| First-time friction | Import a `.conf` / scan a QR, per-device manual key | Install app + paste one pre-auth key (or OAuth tap); exit node = 2 taps |
| Roaming cellular↔WiFi | WireGuard roams (it's the same protocol underneath) | Same roaming, **plus** NAT-traversal/endpoint discovery handled automatically |
| Reboot/always-on | Use Android always-on VPN on the WG profile | Same, app-managed |
| Key/peer management | Manual, per device | Centralized via Headscale control plane + pre-auth keys |

**Conclusion for THIS use case:** both put the decrypted application traffic on the ECS where you can `tcpdump` it. Tailscale's *only* added value over hand-rolled WireGuard is **lower setup friction and automatic NAT traversal/roaming** — which is precisely the user's complaint about the strongSwan flow. Underneath, Tailscale **is** WireGuard, so packet-capture behavior and the "exit node sees decrypted traffic" property are identical. Plain WireGuard with `AllowedIPs=0.0.0.0/0` + MASQUERADE achieves the same sniffing with a slightly clunkier (config-file/QR) onboarding and no centralized roam-friendly identity.

### Q5 — Prior art: "phone → exit node on VPS → sniff/inspect"

- `juanfont/headscale` (★~39.9k) — canonical self-hosted control server; its `ref/routes/` docs explicitly describe configuring a node as an exit node to "route all Internet traffic for another Tailscale node."
- `xADubz-Claude/vpn-gateway` — "Tailscale exit node through ProtonVPN — route device traffic through a VPN" (small repo; demonstrates the exit-node-as-gateway pattern).
- `hesstek/ghostroute` — "A self-hosted Linux gateway that tunnels device traffic through a remote residential [exit]" (small repo; same exit-node gateway pattern).
- Tailscale's own docs market exit nodes for **"Destination logging / increased visibility of traffic"** and "forensic analysis" (https://tailscale.com/kb/1103/exit-nodes) — i.e. the vendor explicitly positions the exit node as a place to observe traffic. Also relevant: Tailscale "Block ads with a Raspberry Pi" guide and "subnet router/exit node" guides all rely on the same decrypt-then-forward-then-(filter/inspect) chain, confirming a sniffer/filter on the exit node sees cleartext.
- General confirmation pattern (well-documented across the WireGuard/Tailscale community): on any exit node you enable `ip_forward` + `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE`; running `tcpdump -i tailscale0` on that host shows clients' forwarded flows in cleartext — the same mechanism a Pi-hole/NextDNS-on-exit-node setup uses to filter per-destination.

### Related internal context (existing project)

- The current working solution is documented in user memory: `vpn-readhand-deployed.md` (场景C VPN 隧穿真机打通, systemd `mjx`, strongSwan IKEv2/IPSec PSK full-tunnel). Tailscale/Headscale would replace the **transport + onboarding**, while the downstream sniffer + `stable/protocol.py` decode pipeline (port 7777) is unaffected — it still tcpdumps the same cleartext 7777 flow on the ECS.
- Game server target: `47.96.0.227:7777` (per task context). Capture filter on the ECS would be `tcpdump -i tailscale0 'host 47.96.0.227 and port 7777'` (or filter by the phone's assigned Tailscale 100.x IP).

## Caveats / Not Found

- **Application-layer encryption is the only real risk, and it is unchanged by Tailscale.** If the mahjong client used TLS to the game server, neither strongSwan nor Tailscale would give you cleartext — you'd see TLS records either way. Since the existing strongSwan sniffer already reads the hand, the 7777 payload is parseable, and Tailscale will expose the identical bytes. Tailscale neither helps nor hurts here.
- **Direct UDP reachability:** the phone must reach the ECS's WireGuard UDP port (default 41641, plus Headscale control on 443/HTTPS). On most cellular/WiFi this works via NAT traversal; if a network blocks UDP entirely, Tailscale falls back to DERP-over-443 (TCP/HTTPS) — slower but keeps the tunnel (and thus the sniff) alive. Verify the Aliyun security group opens the WireGuard UDP port and 443.
- **"Block connections without VPN"** (Android always-on lockdown) guarantees the game traffic never leaks outside the tunnel even momentarily — recommended so sniffing is never silently bypassed on a network change.
- Specific tap counts are approximate (vary by Android skin/version); the qualitative claim "one-time ~10 taps, then roam/reboot-persistent" is solid.
- I could not fetch live blog posts via Jina (reader endpoint returned empty in this environment) and `gh`/exa MCP were unauthenticated; GitHub data came from the public GitHub REST API and primary vendor docs (tailscale.com, headscale.net), which are the authoritative sources for the technical claims above.
