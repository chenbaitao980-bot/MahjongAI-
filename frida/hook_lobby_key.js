/**
 * hook_lobby_key.js — extract the LOBBY-layer (processid 1147) AES key + plaintext.
 *
 * Captures, for every native encryption on libcocos2dlua.so:
 *   - REAL key via OpenSSL AES_set_encrypt_key (game's setAesKey wrapper is
 *     anti-tamper-scrubbed to zeros; the raw key handed to OpenSSL is real),
 *   - plaintext via Encryption::encrypt,
 *   - processid/msgid + pre-encryption payload via Packer32::packMessage.
 * pid=1147 packMsg payload == the lobby login plaintext (the thing we must know
 * to decide if the active path is replayable).
 *
 * Output: /data/local/tmp/.lobby_dump.jsonl
 *
 * Frida 17 compatible: Module.findExportByName(null,..) was removed; we resolve
 * via the module instance + global export + static base offsets.
 */
var OUTPUT = "/data/local/tmp/.lobby_dump.jsonl";
var DONE = false;

// static file offsets in libcocos2dlua.so (srs-key-derivation.md)
var OFF_ENCRYPT = 0x8f5400;
var OFF_SET_AES_KEY = 0x8f5314;
var OFF_AES_SET_ENC_KEY = 0x9f8864;

var SYM_ENCRYPT = "_ZN8universe7network10Encryption7encryptEPKhPhmS3_Pi";
var SYM_PACK = "_ZN8universe7network8Packer3211packMessageEPNS0_9ZhouLuJunE";
var SYM_SET_AES = "_ZN8universe7network10Encryption9setAesKeyEPKhm";

function log(e) {
    // App process (u0_a370) usually cannot write /data/local/tmp; stream to the
    // PC driver via send() instead. Driver writes the local jsonl.
    try { e._rec = 1; send(e); } catch (x) {}
}
function hx(p, n) {
    try { var b = ptr(p).readByteArray(n); if (!b) return ""; return Array.from(new Uint8Array(b)).map(function (c) { return ("0" + c.toString(16)).slice(-2); }).join(""); } catch (x) { return ""; }
}
function tid() { try { return Process.getCurrentThreadId(); } catch (x) { return 0; } }

// resolve a symbol: module-instance export -> global export -> base+offset
function resolveSym(lib, name, fallbackOffset) {
    var p = null;
    try { if (lib && typeof lib.findExportByName === "function") p = lib.findExportByName(name); } catch (e) {}
    if ((!p || p.isNull()) && typeof Module.findGlobalExportByName === "function") {
        try { p = Module.findGlobalExportByName(name); } catch (e) {}
    }
    if ((!p || p.isNull()) && lib && fallbackOffset) p = lib.base.add(fallbackOffset);
    return (p && !p.isNull()) ? p : null;
}

function install() {
    if (DONE) return;
    var lib = Process.findModuleByName("libcocos2dlua.so");
    if (!lib) return;
    send("[lobby] libcocos2dlua.so @ " + lib.base);

    // (A) REAL key: AES_set_encrypt_key(userKey, bits, AES_KEY*)
    var aesSetKey = resolveSym(lib, "AES_set_encrypt_key", OFF_AES_SET_ENC_KEY);
    if (aesSetKey) {
        try {
            Interceptor.attach(aesSetKey, {
                onEnter: function (a) {
                    var bits = a[1].toInt32();
                    if (bits !== 128 && bits !== 192 && bits !== 256) return;
                    log({ type: "aes_set_key", tid: tid(), bits: bits, key: hx(a[0], bits / 8), ts: Date.now() });
                }
            });
            send("[hook] AES_set_encrypt_key @ " + aesSetKey);
        } catch (x) { send("[err] AES_set_encrypt_key: " + x); }
    } else { send("[warn] AES_set_encrypt_key not resolved"); }

    // (B) plaintext + iv: Encryption::encrypt(this, in, out, len, iv, outlen)
    var enc = resolveSym(lib, SYM_ENCRYPT, OFF_ENCRYPT);
    if (enc) {
        try {
            Interceptor.attach(enc, {
                onEnter: function (a) {
                    this.len = a[3].toInt32();
                    this.pt = hx(a[1], this.len);
                    this.iv = hx(a[4], 16);
                    this.objkey = hx(ptr(a[0]).add(0x3b0), 32);
                },
                onLeave: function () {
                    log({ type: "encrypt", tid: tid(), len: this.len, plaintext: this.pt, iv: this.iv, objkey: this.objkey, ts: Date.now() });
                }
            });
            send("[hook] Encryption::encrypt @ " + enc);
        } catch (x) { send("[err] encrypt: " + x); }
    } else { send("[warn] encrypt not resolved"); }

    // (C) processid/msgid + pre-encryption payload: Packer32::packMessage(ZhouLuJun*)
    var pack = resolveSym(lib, SYM_PACK, null);
    if (pack) {
        try {
            Interceptor.attach(pack, {
                onEnter: function (a) {
                    var m = ptr(a[1]);
                    this.pid = m.add(0x10).readU32();
                    this.mid = m.add(0x18).readU32();
                    this.plen = m.add(0x20).readU32();
                    this.pl = (this.plen > 0 && this.plen < 65536) ? hx(m.add(0x30), this.plen) : "";
                },
                onLeave: function () {
                    log({ type: "packMsg", tid: tid(), pid: this.pid, msgid: this.mid, paylen: this.plen, payload: this.pl, ts: Date.now() });
                }
            });
            send("[hook] packMessage @ " + pack);
        } catch (x) { send("[err] packMessage: " + x); }
    } else { send("[warn] packMessage not resolved"); }

    // (D) optional: setAesKey wrapper (to confirm scrub vs real)
    var sak = resolveSym(lib, SYM_SET_AES, OFF_SET_AES_KEY);
    if (sak) {
        try {
            Interceptor.attach(sak, {
                onEnter: function (a) {
                    var l = a[2].toInt32();
                    if (l === 16 || l === 24 || l === 32) log({ type: "setAesKey_wrapper", tid: tid(), len: l, key: hx(a[1], l), ts: Date.now() });
                }
            });
            send("[hook] setAesKey wrapper @ " + sak);
        } catch (x) {}
    }

    DONE = true;
    send("[lobby] hooks installed -> " + OUTPUT);
}

install();
var n = 0;
var t = setInterval(function () { if (DONE) { clearInterval(t); return; } install(); if (++n > 30) { clearInterval(t); send("[lobby] gave up"); } }, 2000);
send("[lobby] waiting for libcocos2dlua.so ...");
