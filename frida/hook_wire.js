/**
 * libc-level TCP capture hook for SRS key extraction
 * Works on x86_64 emulator with native bridge (ARM64 libcocos2dlua.so invisible to Frida)
 * Captures all send/recv to port 7777 (game server) 
 */
var OUTPUT = "/data/local/tmp/.srs_wire.jsonl";
var TARGET_PORT = 7777;
var fdMap = {};  // fd -> "IP:port"

// ===== Helper =====
function toHex(buf, len) {
    try {
        var bytes = Memory.readByteArray(buf, len);
        if (!bytes) return "";
        var arr = new Uint8Array(bytes);
        return Array.from(arr).map(function(b) { return ("0"+b.toString(16)).slice(-2); }).join("");
    } catch(e) { return ""; }
}

function wireLog(entry) {
    try {
        var f = new File(OUTPUT, "a");
        f.write(JSON.stringify(entry) + "\n");
        f.flush();
        f.close();
    } catch(e) {}
}

// ===== 1. Hook connect() to track TCP connections to port 7777 =====
var connectFn = Module.findGlobalExportByName("connect");
if (connectFn) {
    Interceptor.attach(connectFn, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            var sa = args[1];
            // sockaddr_in: family(2B) + port(2B BE) + addr(4B) + zero(8B)
            this.family = sa.readU16();
            this.port = ((sa.add(2).readU8() << 8) | sa.add(3).readU8());
        },
        onLeave: function(ret) {
            if (ret.toInt32() === 0 && this.family === 2) { // AF_INET = 2
                if (this.port === TARGET_PORT) {
                    fdMap[this.fd] = true;
                    wireLog({type: "connect", fd: this.fd, port: this.port, ts: Date.now()});
                    console.log("[connect] fd=" + this.fd + " port=" + this.port);
                }
            }
        }
    });
    console.log("[+] connect hooked (checking AF_INET)");
} else {
    console.log("[-] connect NOT FOUND");
}

// ===== 2. Hook send/sendto/write to capture outgoing data =====
function hookSend(name) {
    var fn = Module.findGlobalExportByName(name);
    if (fn) {
        Interceptor.attach(fn, {
            onEnter: function(args) {
                this.fd = args[0].toInt32();
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function(ret) {
                var n = ret.toInt32();
                if (n > 0 && n < 65536 && fdMap[this.fd]) {
                    wireLog({type: "send", fd: this.fd, len: n, data: toHex(this.buf, n), ts: Date.now()});
                    console.log("[" + name + "] len=" + n + " hex=" + toHex(this.buf, Math.min(n,48)));
                }
            }
        });
        console.log("[+] " + name + " hooked");
    }
}
hookSend("send");
hookSend("sendto");
hookSend("write");

// ===== 3. Hook recv/recvfrom/read to capture incoming data =====
function hookRecv(name) {
    var fn = Module.findGlobalExportByName(name);
    if (fn) {
        Interceptor.attach(fn, {
            onEnter: function(args) {
                this.fd = args[0].toInt32();
                this.buf = args[1];
            },
            onLeave: function(ret) {
                var n = ret.toInt32();
                if (n > 0 && n < 65536 && fdMap[this.fd]) {
                    wireLog({type: "recv", fd: this.fd, len: n, data: toHex(this.buf, n), ts: Date.now()});
                    console.log("[" + name + "] len=" + n + " hex=" + toHex(this.buf, Math.min(n,48)));
                }
            }
        });
        console.log("[+] " + name + " hooked");
    }
}
hookRecv("recv");
hookRecv("recvfrom");
hookRecv("read");

console.log("\n===== Hooks installed (libc level) =====");
console.log("Waiting for TCP traffic to port " + TARGET_PORT + "...");
console.log("Output: " + OUTPUT);
