/**
 * hook_hand.js — siphon the player's OWN game frames from inside the game process.
 *
 * The game's 0x2bc0/0x2bc1 frames (which carry the player's own hand) are
 * PLAINTEXT on the wire (stable mode reads them passively). So we hook the
 * RECV path (libc recv/read; libuv uses these under the hood) and capture the
 * raw incoming bytes for the game-server connection (47.96.0.227:7777). On the
 * PC we reassemble + parse with MJProtocol to confirm the hand is present.
 *
 * This is the on-device SIPHON validation: read the hand from the phone's own
 * session (no 2nd connection, no kick, any network).
 *
 * Streams to the PC driver via send().
 */
var DONE = false;
var GAME_IP = "47.96.0.227";
var fdMap = {};   // fd -> "ip:port"

function hx(p, n) { try { if (n > 200000) n = 200000; var b = ptr(p).readByteArray(n); if (!b) return ""; return Array.from(new Uint8Array(b)).map(function (c) { return ("0" + c.toString(16)).slice(-2); }).join(""); } catch (x) { return ""; } }
function rec(e) { try { e._rec = 1; send(e); } catch (x) {} }

function install() {
    if (DONE) return;

    var connect = Module.findGlobalExportByName ? Module.findGlobalExportByName("connect") : null;
    var recv = Module.findGlobalExportByName ? Module.findGlobalExportByName("recv") : null;
    var read = Module.findGlobalExportByName ? Module.findGlobalExportByName("read") : null;
    if (!connect && !recv) {
        // libc may need explicit module
        try { connect = Module.getExportByName("libc.so", "connect"); } catch (e) {}
        try { recv = Module.getExportByName("libc.so", "recv"); } catch (e) {}
        try { read = Module.getExportByName("libc.so", "read"); } catch (e) {}
    }

    if (connect) {
        Interceptor.attach(connect, {
            onEnter: function (a) { this.fd = a[0].toInt32(); this.addr = a[1]; },
            onLeave: function (r) {
                try {
                    var fam = this.addr.readU16();
                    var port = (this.addr.add(2).readU8() << 8) | this.addr.add(3).readU8();
                    var ip = this.addr.add(4).readU8() + "." + this.addr.add(5).readU8() + "." + this.addr.add(6).readU8() + "." + this.addr.add(7).readU8();
                    fdMap[this.fd] = ip + ":" + port;
                    if (ip === GAME_IP) { rec({ type: "conn", fd: this.fd, addr: fdMap[this.fd], ts: Date.now() }); send("[conn] fd=" + this.fd + " -> " + fdMap[this.fd]); }
                } catch (e) {}
            }
        });
        send("[hook] connect");
    }

    var gameFds = {};  // fds that have carried 0x4001-framed traffic
    function attachRecvLike(fn, name) {
        Interceptor.attach(fn, {
            onEnter: function (a) { this.fd = a[0].toInt32(); this.buf = a[1]; },
            onLeave: function (r) {
                var n = r.toInt32();
                if (n <= 0 || n > 200000) return;
                var fd = this.fd;
                var known = gameFds[fd] || (fdMap[fd] && fdMap[fd].indexOf(GAME_IP) === 0);
                var headHex = "";
                if (!known) {
                    // peek first up-to-64 bytes; if a 0140 frame flag appears, it's the game protocol
                    try { var pk = ptr(this.buf).readByteArray(Math.min(n, 64)); headHex = pk ? Array.from(new Uint8Array(pk)).map(function (c) { return ("0" + c.toString(16)).slice(-2); }).join("") : ""; } catch (e) {}
                    if (headHex.indexOf("0140") < 0) return;
                    gameFds[fd] = 1;  // sticky: capture everything on this fd from now on
                    send("[gamefd] fd=" + fd + " marked (addr=" + (fdMap[fd] || "?") + ")");
                }
                rec({ type: "recv", fn: name, fd: fd, len: n, addr: fdMap[fd] || "?", data: hx(this.buf, n), ts: Date.now() });
            }
        });
        send("[hook] " + name);
    }
    var recvfrom = null;
    try { recvfrom = Module.findGlobalExportByName("recvfrom"); } catch (e) {}
    if (!recvfrom) { try { recvfrom = Module.getExportByName("libc.so", "recvfrom"); } catch (e) {} }
    if (recv) attachRecvLike(recv, "recv");
    if (read) attachRecvLike(read, "read");
    if (recvfrom) attachRecvLike(recvfrom, "recvfrom");

    DONE = true;
    send("[hand] siphon hooks installed (game server " + GAME_IP + ")");
}

install();
var n = 0;
var t = setInterval(function () { if (DONE) { clearInterval(t); return; } install(); if (++n > 30) { clearInterval(t); send("[hand] gave up"); } }, 2000);
send("[hand] waiting ...");
