# Code Protection and Packaging

## Core boundary

If someone physically gets the soft router and also gets root access, pure software packaging cannot guarantee that they "cannot see the code".

What is achievable:

* make casual browsing hard
* remove plain `.py` distribution
* bind builds to devices or activation
* move sensitive logic or keys off-device

What is not realistically guaranteed:

* perfect secrecy of all local logic on an attacker-controlled Linux box

## Packaging options

### 1. Keep Python source bundle

Form:

* current repo-style `tar.gz`
* optional `ipk` wrapper or custom image install hook

Pros:

* simplest
* easiest to debug and support
* most compatible with OpenWrt variants

Cons:

* code is plainly visible

### 2. Freeze into executable with PyInstaller

External doc notes:

* PyInstaller states it can bundle the app and dependencies into a single folder or a single executable.
* In one-file mode, the executable contains an embedded archive and extracts support files to a temporary folder at runtime.
* PyInstaller is not a cross-compiler, so Linux targets must be built on Linux.

Implication:

* this is good for "single binary launch"
* it improves convenience and removes obvious source trees
* it is not strong code protection by itself, because the payload is still recoverable enough for a determined attacker

### 3. Compile with Nuitka

External doc notes:

* Nuitka says binaries can run independently of the Python installation in `standalone`, `onefile`, or `app` mode.

Implication:

* stronger than shipping plain source
* often a better fit than PyInstaller when the goal includes raising reverse-engineering cost
* Linux portability still needs careful target-by-target validation

### 4. Obfuscate with PyArmor

External doc notes:

* PyArmor documents irreversible obfuscation, C function conversion, and script binding.
* Script binding can tie outputs to machines or expiration.

Implication:

* useful as an extra layer on top of Python delivery or compiled delivery
* improves resistance to direct reading
* still not enough alone if the whole runtime environment is attacker-controlled

## Practical protection stack

### Baseline

* package as `ipk` or custom install bundle
* move secrets out of repo defaults
* use service wrapper for one-click start and boot-start

### Recommended protection

* compile core local agent with Nuitka for Linux/OpenWrt-capable targets where feasible
* obfuscate remaining Python with PyArmor if some scripts must stay Python
* strip symbols and separate config from code
* store activation material and high-value secrets on the server side

### Higher bar

* device binding / license activation
* signed update channel
* server-issued short-lived credentials
* split architecture so the router only runs collection/proxy code and sensitive decision logic stays remote

## Packaging formats to compare

### A. `tar.gz` installer

* easiest
* already aligned with repo
* good for internal deployment

### B. OpenWrt `ipk`

* best for router-native install/uninstall/upgrade
* fits procd startup model
* slightly more packaging work

### C. Custom OpenWrt image / ImageBuilder output

* best "appliance-like" user experience
* strongest control over installed files and startup state
* highest maintenance cost per target architecture

### D. Container image

* good on x86 soft routers/NAS
* poor fit on many small OpenWrt devices
* not the best universal default

## Recommendation

If the product target is "many different soft routers":

1. first deliver `tar.gz` plus `ipk`
2. then evaluate per-architecture compiled delivery
3. only do custom firmware images for the most common router targets

If the product target is "appliance sold by us":

1. custom image
2. compiled agent
3. device binding + remote activation

This is the only path that gets close to "users cannot casually inspect code", but even then it is still a hardening strategy, not a mathematical guarantee.
