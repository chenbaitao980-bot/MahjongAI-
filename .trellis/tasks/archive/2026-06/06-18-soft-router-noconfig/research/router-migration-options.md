# Router Migration Options

## Repo facts

### 1. Current soft-router-capable path already exists

The repo already has a router deployment path centered on:

* `remote/extractor/package_extractor.py`
* `remote/extractor/install_openwrt.sh`
* `remote/extractor/install_linux.sh`
* `remote/extractor/DEPLOY.md`

What it already does:

* bundles extractor runtime files into `mahjong-extractor-bundle.tar.gz`
* can pre-write extractor config with `--relay-url`
* can generate matching relay config with `--write-relay-config`
* installs as a boot service on OpenWrt (`procd`) or Linux (`systemd`)
* can self-check whether phone traffic really passes the router

Conclusion:

* "move to other soft routers" is already feasible for the passive extractor architecture
* this path is closest to productization as a single deployment bundle

### 2. Current hotspot no-config path is a different architecture

The current PC-hotspot no-config flow lives under `remote/noconfig/hijack/*`.

Observed components:

* `run_hijack.py`: one-click launcher for setup-period MITM
* `setup_mitm.py`: DNS hijack + HTTPS hot-update MITM + NetConf patch
* `dns_divert.py`: WinDivert interception for hardcoded DNS
* `ecs_proxy.py` / `tcp_proxy.py` / `ecs_run.py`: ECS-side or router-side traffic proxy and relay push
* `remote/noconfig/app.py`: admin API, multi-user state, spectator/process coordination

Conclusion:

* "same as connecting to the PC hotspot" means reproducing this hijack chain, not just moving extractor
* this route needs more local services and tighter network control than the passive extractor route

## Candidate architectures

### Approach A: Router-resident extractor + cloud relay

How it works:

1. phone traffic passes through soft router
2. router runs extractor and passively captures `tcp port 7777`
3. router extracts auth/session/snapshots
4. router pushes snapshots to cloud relay
5. admin UI reads data from relay

Pros:

* already partially implemented in repo
* easiest to package and auto-start
* works on OpenWrt / x86 Linux / NAS-like systems
* smallest local service footprint
* easiest to turn into `tar.gz` installer, `ipk`, or container

Cons:

* not literally the same as the current hotspot hot-update/MITM flow
* depends on traffic physically traversing the router
* if the user wants "no-config client redirection via hot-update", this route is insufficient by itself

Fit:

* best if priority is stable deployment and low maintenance

### Approach B: Full no-config hijack stack on soft router

How it works:

1. soft router provides the WiFi or sits as the forced gateway
2. router runs local DNS hijack / DNS divert equivalent
3. router serves HTTPS hot-update content and patches `NetConf`
4. phone completes one-time no-config bootstrap through router
5. router or ECS then proxies lobby/game traffic and feeds relay/admin

Pros:

* closest to "connect to router == connect to this PC hotspot"
* preserves existing no-config mental model
* can keep phone-side behavior nearly unchanged

Cons:

* highest implementation and operations complexity
* Windows-only pieces such as WinDivert need router-native replacements
* requires certificate, DNS, iptables/nftables, reverse proxy, and startup orchestration
* more difficult to harden and more difficult to support across heterogeneous routers

Fit:

* best if priority is strict equivalence with the current PC-hotspot experience

### Approach C: VPN-first soft-router / cloud edge path

Repo evidence:

* `package_extractor.py` already supports `--with-vpn`
* `remote/extractor/vpn/README.md` describes a strongSwan IKEv2 flow

How it works:

1. phone uses VPN to route game traffic to a controlled edge
2. edge host/router runs extractor and relay
3. traffic becomes visible without depending on local hotspot mode

Pros:

* avoids some local WiFi/hotspot constraints
* can work across 4G / arbitrary WiFi
* can be paired with Always-on VPN for a "just stays connected" experience

Cons:

* not the same as "user just connects to router WiFi and is done"
* may require client-side VPN configuration or app support
* built-in system VPN and split-tunnel behavior depend on client capabilities

External note:

* strongSwan documents that split tunneling is supported in strongSwan-based Android clients and that the client proposes `0.0.0.0/0`, with server narrowing applied after that.

Fit:

* best if priority is broader network portability rather than hotspot equivalence

## Recommendation

Recommended sequence:

1. Productize Approach A first
2. Evaluate whether user-visible requirements truly demand Approach B
3. Keep Approach C as an optional remote-access extension, not the default base architecture

Why:

* Approach A is already closest to the current repo shape
* Approach B should only be chosen if "same as PC hotspot" is a hard requirement, not just a preference
* Approach C is powerful but changes the user journey
