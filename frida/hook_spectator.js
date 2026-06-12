/**
 * hook_spectator.js — capture the spectator game record (incoming) to test
 * whether it contains a player's HIDDEN HAND.
 *
 * The spectator record is INCOMING: server -> decrypt -> (merge fragments) ->
 * zlib-inflate -> game record. We hook BOTH Encryption::encrypt and
 * Encryption::decrypt and capture the OUTPUT buffer:
 *   - decrypt output = the decrypted (still zlib-compressed) payload -> we
 *     zlib-decompress it on the PC (run side) and inspect for hand tiles.
 * We also try the game's own zlib uncompress/inflate (module-instance first).
 *
 * Streams records to the PC driver via send().
 */
var DONE = false;
var OFF_ENCRYPT = 0x8f5400;
var SYM_ENCRYPT = "_ZN8universe7network10Encryption7encryptEPKhPhmS3_Pi";
var SYM_DECRYPT = "_ZN8universe7network10Encryption7decryptEPKhPhmS3_Pi";

function hx(p, n) {
    try { if (n > 300000) n = 300000; var b = ptr(p).readByteArray(n); if (!b) return ""; return Array.from(new Uint8Array(b)).map(function (c) { return ("0" + c.toString(16)).slice(-2); }).join(""); } catch (x) { return ""; }
}
function rec(e) { try { e._rec = 1; send(e); } catch (x) {} }
function resolveLocalFirst(lib, name, off) {
    var p = null;
    try { if (lib && typeof lib.findExportByName === "function") p = lib.findExportByName(name); } catch (e) {}
    if ((!p || p.isNull()) && typeof Module.findGlobalExportByName === "function") { try { p = Module.findGlobalExportByName(name); } catch (e) {} }
    if ((!p || p.isNull()) && lib && off) p = lib.base.add(off);
    return (p && !p.isNull()) ? p : null;
}

function attachCrypto(addr, dir) {
    // The game uses ONE CFB function for both directions; capture BOTH input
    // and output. For outgoing: inp=plaintext. For incoming: out=plaintext
    // (often zlib -> decompress on PC). We log both and decide on the run side.
    Interceptor.attach(addr, {
        onEnter: function (a) {
            this.inp = a[1]; this.out = a[2]; this.len = a[3].toInt32();
        },
        onLeave: function () {
            if (this.len <= 0 || this.len > 300000) return;
            rec({ type: dir, len: this.len, inp: hx(this.inp, this.len), out: hx(this.out, this.len), ts: Date.now() });
        }
    });
}

function install() {
    if (DONE) return;
    var lib = Process.findModuleByName("libcocos2dlua.so");
    if (!lib) return;
    send("[spec] base @ " + lib.base);

    var enc = resolveLocalFirst(lib, SYM_ENCRYPT, OFF_ENCRYPT);
    if (enc) { try { attachCrypto(enc, "encrypt"); send("[hook] encrypt @ " + enc); } catch (x) { send("[err] enc " + x); } }

    var dec = resolveLocalFirst(lib, SYM_DECRYPT, null);
    if (dec) { try { attachCrypto(dec, "decrypt"); send("[hook] decrypt @ " + dec); } catch (x) { send("[err] dec " + x); } }
    else { send("[warn] decrypt symbol not found (will rely on zlib hooks)"); }

    // game's own zlib first (module instance), then system
    var unc = resolveLocalFirst(lib, "uncompress", null);
    if (unc) {
        try {
            Interceptor.attach(unc, {
                onEnter: function (a) { this.dest = a[0]; this.destLenP = a[1]; },
                onLeave: function () { try { var n = ptr(this.destLenP).readU32(); if (n > 0 && n < 500000) rec({ type: "unzip", fn: "uncompress", outLen: n, data: hx(this.dest, n), ts: Date.now() }); } catch (e) {} }
            });
            send("[hook] uncompress @ " + unc);
        } catch (x) {}
    }
    var infl = resolveLocalFirst(lib, "inflate", null);
    if (infl) {
        try {
            Interceptor.attach(infl, {
                onEnter: function (a) { this.s = ptr(a[0]); try { this.no = this.s.add(24).readPointer(); this.ao = this.s.add(32).readU32(); } catch (e) { this.no = null; } },
                onLeave: function () { try { if (!this.no) return; var prod = this.ao - this.s.add(32).readU32(); if (prod > 0 && prod < 500000) rec({ type: "unzip", fn: "inflate", outLen: prod, data: hx(this.no, prod), ts: Date.now() }); } catch (e) {} }
            });
            send("[hook] inflate @ " + infl);
        } catch (x) {}
    }

    DONE = true;
    send("[spec] hooks installed");
}

install();
var n = 0;
var t = setInterval(function () { if (DONE) { clearInterval(t); return; } install(); if (++n > 30) { clearInterval(t); send("[spec] gave up"); } }, 2000);
send("[spec] waiting ...");
