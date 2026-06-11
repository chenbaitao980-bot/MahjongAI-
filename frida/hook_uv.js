// Minimal Frida script — hook uv_write to capture SRS wire bytes
var HIT = 0;
Interceptor.attach(Module.findExportByName(null, "uv_write"), {
    onEnter(args) {
        var nbufs = args[3].toInt32();
        if (nbufs <= 0 || nbufs > 10) return;
        var bufs = ptr(args[2]);
        for (var i = 0; i < nbufs; i++) {
            var base = bufs.add(i * 0x10).readPointer();
            var blen = parseInt(bufs.add(i * 0x10 + 8).readU64());
            if (blen > 0 && blen < 65536) {
                HIT++;
                var bytes = base.readByteArray(blen);
                var hex = Array.from(new Uint8Array(bytes))
                    .map(function(b) { return ("0"+b.toString(16)).slice(-2); }).join("");
                send(JSON.stringify({type:"uv_write", n:HIT, len:blen, data:hex}));
            }
        }
    }
});
send("[init] uv_write hook active");
