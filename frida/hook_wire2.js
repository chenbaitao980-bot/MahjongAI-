var fdMap = {};

function toHex(buf, len) {
    try {
        var bytes = Memory.readByteArray(buf, len);
        var arr = new Uint8Array(bytes);
        return Array.from(arr).map(function(b) { return ("0"+b.toString(16)).slice(-2); }).join("");
    } catch(e) { return ""; }
}

// Hook ALL connect (AF_INET only)
var connectFn = Module.findGlobalExportByName("connect");
if (connectFn) {
    Interceptor.attach(connectFn, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            var sa = args[1];
            this.family = sa.readU16();
            if (this.family === 2) {
                this.port = ((sa.add(2).readU8() << 8) | sa.add(3).readU8());
                var ip = sa.add(4).readU8() + "." + sa.add(5).readU8() + "." + sa.add(6).readU8() + "." + sa.add(7).readU8();
                this.ip = ip;
            }
        },
        onLeave: function(ret) {
            if (ret.toInt32() === 0 && this.family === 2) {
                fdMap[this.fd] = this.ip + ":" + this.port;
                console.log("[connect] fd=" + this.fd + " -> " + this.ip + ":" + this.port);
            }
        }
    });
    console.log("[+] connect hooked");
}

// Hook send/recv for captured fds
function hookIO(name) {
    var fn = Module.findGlobalExportByName(name);
    if (fn) {
        Interceptor.attach(fn, {
            onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; this.len = args[2].toInt32(); },
            onLeave: function(ret) {
                var n = ret.toInt32();
                if (n > 0 && fdMap[this.fd]) {
                    console.log("[" + name + "] fd=" + this.fd + " len=" + n + " dst=" + fdMap[this.fd] + " hex=" + toHex(this.buf, Math.min(n, 64)));
                }
            }
        });
    }
}
hookIO("send"); hookIO("sendto"); hookIO("write");
hookIO("recv"); hookIO("recvfrom"); hookIO("read");
console.log("[+] io hooks installed");
console.log("Waiting for TCP connections...");
