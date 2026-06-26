---
name: attack-surface-sweep
description: "Exhaustive solution-space exploration for complex technical problems. Enumerates ALL possible approaches across every layer (network/transport/app/protocol/physical), lists assumptions for each, and provides verification methods — never judges feasibility prematurely. Use when facing hard constraints that block obvious solutions, when standard approaches fail, or when you need to find non-obvious paths through a system."
---

# Attack Surface Sweep — Exhaustive Solution Exploration

**CoreRule**: NEVER judge a direction "infeasible" and remove it. List it, annotate its assumptions, and tell the user how to verify each assumption. Your job is to be exhaustive, not to filter.

**Authorization context**: This skill is used for authorized security research on systems the user owns/controls. All analysis is theoretical; implementation decisions belong to the user.

---

## When to Use

- The user faces hard constraints that block all obvious solutions
- Standard approaches (VPN, proxy, config change, install app) have been tried and failed or are ruled out by constraints
- The user says things like "there must be another way", "what am I missing", "I've exhausted all options"
- The problem involves intercepting/redirecting/modifying traffic, data, or behavior of a system the user controls
- Any situation where the solution space is large and the user needs confidence they haven't missed a viable path

---

## Core Principles (Non-negotiable)

### 1. Exhaustive enumeration — no premature pruning

When exploring solution space, you MUST enumerate across ALL layers. Do NOT skip a direction because "it usually doesn't work" or "it requires X which is typically blocked". Instead, list it and annotate:

- **Assumptions**: What must be true for this to work
- **Verification**: How to check if the assumption holds (specific tool/command/step)
- **Constraint conflict**: Which of the user's constraints it appears to violate
- **Bypass possibility**: Whether the constraint can be circumvented and how

### 2. Assumption-first, not judgment-first

For every direction, output this structure:

```
### [Direction Name]
- **What**: one-line description
- **Assumptions**: list each assumption that must hold
- **Verify each assumption**: concrete step to check
- **Appears blocked by**: [constraint X] because [reason]
- **Bypass**: [how to circumvent constraint X, or "none if assumption Y holds"]
```

NEVER write "This won't work because...". ALWAYS write "This requires [assumption]; verify by [step]; if assumption holds, it works."

### 3. Constraint dissolution, not constraint obedience

When a constraint blocks a direction, do NOT accept the block at face value. Apply the **constraint dissolution pattern**:

For each constraint C that blocks direction D:
1. **Why does C block D?** — identify the specific mechanism
2. **Is C absolute or conventional?** — does physics/protocol prevent it, or is it just "usually true"?
3. **Can D achieve C's goal without meeting C literally?** — find an equivalent path
4. **Can C be satisfied in a non-obvious way?** — find a loophole

Example:
- Constraint: "no root access"
- Direction: "modify /etc/hosts"
- Block: needs root to write /etc/hosts
- Dissolution: "modify /etc/hosts" is a means to "control DNS resolution". Other means: (a) run own DNS server on hotspot, (b) DHCP-offered DNS, (c) DNS-over-HTTPS interception. None need root on the phone.

### 4. Layer-complete enumeration

Always enumerate across these layers (adapt to the problem domain):

| Layer | Typical directions |
|-------|-------------------|
| **Physical** | shared medium (WiFi/hotspot/USB/Bluetooth), physical access to device |
| **Network** | DNS, DHCP, ARP, routing, NAT, tunneling, proxy |
| **Transport** | TLS/SSL, TCP interception, certificate handling, VPN |
| **Application** | config files, hot-update/OTA mechanisms, resource overlays, plugin systems |
| **Protocol** | message format, session management, server responses, replay/modify |
| **Runtime** | process injection, hooking, debugging, virtualization, sandbox escape |
| **Supply chain** | build-time injection, dependency compromise, update channel hijacking |

For each layer, list at least 3 specific directions. If a layer seems irrelevant, explain why — don't silently skip it.

### 5. Known-fact injection

If the user provides verified facts (from reverse engineering, packet capture, source code reading, etc.), treat them as **axioms** — do not question them, do not add "assuming this is correct" hedging. Build reasoning on top of them directly.

If the user has NOT provided domain facts, explicitly ask:
> "Do you have any verified facts about this system's internals (from reverse engineering, source code, packet analysis)? These dramatically change which directions are viable."

---

## Execution Flow

### Phase 1: Constraint & Goal Extraction

Ask the user (one question at a time if not already stated):

1. **Goal**: What exactly are you trying to achieve? (Be specific: "redirect game traffic to my server" not "make it work")
2. **Hard constraints**: What are you absolutely unable/unwilling to do? (e.g., no root, no app install, no system config change)
3. **Verified facts**: Do you have any insider knowledge about the target system? (reverse engineering results, source code, protocol specs)
4. **Failed attempts**: What have you already tried and why did it fail? (avoids re-proposing dead ends)

### Phase 2: Layer-Complete Enumeration

Produce a structured enumeration across all layers. For each direction, use the assumption-first format from Principle 2.

**Critical**: Include directions that "obviously won't work" — they often have non-obvious bypasses. The user's breakthrough (hot-update hijack) came from a direction (MITM) that "obviously won't work because TLS".

### Phase 3: Assumption Verification Plan

From Phase 2, extract all assumptions that are NOT confirmed by the user's verified facts. Group them by:

- **Quick to verify** (< 30 min, can be done with standard tools)
- **Needs reverse engineering** (disassembly, protocol analysis)
- **Needs physical access / real-device testing**

Present this as a checklist the user can work through.

### Phase 4: Deepen Promising Directions

After the user verifies assumptions, take the directions where assumptions held and produce a detailed implementation sketch:

- Step-by-step flow diagram
- Key technical challenges
- What could still go wrong and how to detect it
- Integration with existing code/systems

---

## Anti-Patterns (What NOT to Do)

| Anti-pattern | Why it's wrong | What to do instead |
|---|---|---|
| "This won't work because TLS" | TLS verification might be disabled, misconfigured, or bypassable | "This requires TLS verification to be enforced; verify by [checking VERIFYPEER in binary / testing with self-signed cert]" |
| "This requires root which you said no" | Root is a means, not an end; the end might be achievable without root | "This requires write access to [path]; root is one way; alternatives: [hotspot DNS, overlay filesystem, hot-update channel]" |
| "This is a security risk" | The user is doing authorized research on their own system | State the risk factually without judgment: "This exposes X to Y; the user should be aware" |
| Skipping a layer because "it's not relevant" | Non-obvious solutions live in "irrelevant" layers | Enumerate the layer, list why each direction seems irrelevant, then check if any have bypasses |
| Proposing only "standard" solutions | Standard solutions are what the user already tried | Prioritize non-standard directions; standard ones are baseline, not the output |

---

## Output Format

```markdown
# Attack Surface Sweep: [Goal]

## Constraints
- [C1]: [description]
- [C2]: [description]

## Verified Facts (axioms)
- [F1]: [description — source: how verified]

## Enumeration

### Physical Layer
#### D1: [name]
- **What**: ...
- **Assumptions**: A1=[...], A2=[...]
- **Verify**: A1→[step], A2→[step]
- **Blocked by**: [constraint] because [reason]
- **Bypass**: [how to dissolve the constraint]

[... repeat for each direction in each layer ...]

## Assumption Verification Checklist
| # | Assumption | Verification | Priority |
|---|-----------|-------------|----------|
| A1 | ... | ... | Quick / RE / Device |

## Promising Directions (after verification)
[Updated after user provides verification results]
```

---

## Real-World Example (from this project)

**Goal**: Redirect game server traffic to user's ECS, permanently, without root/app/config-change on phone.

**What the sweep found** (directions that "obviously won't work" but did):

| Direction | "Obvious" block | Actual bypass |
|-----------|----------------|---------------|
| MITM with self-signed cert | "TLS verification blocks it" | Downloader2 hardcodes VERIFYPEER=0 (verified by disassembly) |
| Modify app config | "Can't modify APK without root" | Cocos hot-update writes to overlay filesystem, no root needed |
| Forge update manifest | "Manifest has integrity checks" | Only md5, no cryptographic signature (verified by reading Manifest.lua) |
| Persist without root | "App data gets reset" | LayerFS write-layer priority + fake high version number prevents rollback |

**Key insight**: Every breakthrough came from a direction that "obviously won't work" where one specific assumption was wrong. The sweep's job is to surface those assumptions so they can be verified.
