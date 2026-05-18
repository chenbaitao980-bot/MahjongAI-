/**
 * Frida hook script for intercepting game network data.
 *
 * Hooks libc recv() to capture TCP packets from the game server.
 * Captured data is written to a JSONL file for the host to consume.
 *
 * Usage: loaded by frida-gadget in script mode via gadget_config.json
 */

var GAME_PORT = 7777;
var OUTPUT_PATH = "/data/local/tmp/.game_capture.jsonl";

var recvPtr = Module.findExportByName("libc.so", "recv");
if (recvPtr) {
    var fdPortCache = {};

    function getSocketPort(fd) {
        if (fdPortCache[fd] !== undefined) {
            return fdPortCache[fd];
        }
        try {
            var addr = Socket.peerAddress(fd);
            if (addr && addr.port) {
                fdPortCache[fd] = addr.port;
                return addr.port;
            }
        } catch (e) {}
        fdPortCache[fd] = 0;
        return 0;
    }

    Interceptor.attach(recvPtr, {
        onEnter: function (args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave: function (retval) {
            var bytesRead = retval.toInt32();
            if (bytesRead <= 0) return;

            var port = getSocketPort(this.fd);
            if (port !== GAME_PORT) return;

            try {
                var data = this.buf.readByteArray(bytesRead);
                var hex = Array.from(new Uint8Array(data))
                    .map(function (b) { return ("0" + b.toString(16)).slice(-2); })
                    .join("");

                var entry = JSON.stringify({
                    ts: Date.now(),
                    fd: this.fd,
                    port: port,
                    len: bytesRead,
                    hex: hex,
                });

                var f = new File(OUTPUT_PATH, "a");
                f.write(entry + "\n");
                f.flush();
                f.close();
            } catch (e) {}
        },
    });

    send("[hook_recv] attached to recv() - filtering port " + GAME_PORT);
} else {
    send("[hook_recv] ERROR: recv not found in libc.so");
}
