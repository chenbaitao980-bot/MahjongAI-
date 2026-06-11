/**
 * SRS hook — robust version: waits for libcocos2dlua.so to load
 */
var OUTPUT = "/data/local/tmp/.srs_dump.jsonl";
var HIT = false;

function log(entry) {
    try {
        var f = new File(OUTPUT, "a");
        f.write(JSON.stringify(entry) + "\n");
        f.flush();
        f.close();
    } catch(e) {}
}

function toHex(ptr, len) {
    try {
        var bytes = ptr.readByteArray(len);
        if (!bytes) return "";
        return Array.from(new Uint8Array(bytes))
            .map(function(b) { return ("0"+b.toString(16)).slice(-2); }).join("");
    } catch(e) { return ""; }
}

function installAllHooks() {
    if (HIT) return;
    
    // 1. setAesKey
    var p = Module.findExportByName(null, "_ZN8universe7network10Encryption9setAesKeyEPKhm");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                send("[setAesKey] len=" + a[2].toInt32());
                log({type:"setAesKey",len:a[2].toInt32(),key:toHex(a[1],a[2].toInt32()),ts:Date.now()});
            }
        });
        send("[hook] setAesKey");
    }

    // 2. encrypt
    p = Module.findExportByName(null, "_ZN8universe7network10Encryption7encryptEPKhPhmS3_Pi");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                this.pt = toHex(a[1], a[3].toInt32());
                this.iv = toHex(a[4], 16);
                this.len = a[3].toInt32();
                this.res = a[5];
            },
            onLeave: function() {
                log({type:"encrypt", plaintext:this.pt, len:this.len, iv:this.iv, result:this.res.readInt(), ts:Date.now()});
            }
        });
        send("[hook] encrypt");
    }

    // 3. sendMessage(int,int,int,AUpdates*)
    p = Module.findExportByName(null, "_ZN8universe7network10GuoPengFei11sendMessageEiiiPNS0_8AUpdatesE");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                var updates = ptr(a[4]);
                var dp = updates.readPointer();
                var cur = updates.add(8).readU64();
                var ts = updates.add(0x10).readU64();
                var pl = cur > 0 ? toHex(dp, parseInt(cur)) : "";
                log({type:"sendMsg", pid:a[1].toInt32(), appid:a[2].toInt32(), msgid:a[3].toInt32(), paylen:parseInt(cur), payload:pl, ts:Date.now()});
            }
        });
        send("[hook] sendMsg(stream)");
    }

    // 4. sendMessage(ZhouLuJun*)
    p = Module.findExportByName(null, "_ZN8universe7network10GuoPengFei11sendMessageEPNS0_9ZhouLuJunE");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                var m = ptr(a[1]);
                var pid = m.add(0x10).readU32();
                var aid = m.add(0x14).readU32();
                var mid = m.add(0x18).readU32();
                var plen = m.add(0x20).readU32();
                var pl = plen > 0 ? toHex(m.add(0x30), plen) : "";
                log({type:"sendMsg_ZLJ", pid:pid, appid:aid, msgid:mid, paylen:plen, payload:pl, ts:Date.now()});
            }
        });
        send("[hook] sendMsg(ZLJ)");
    }

    // 5. packMessage
    p = Module.findExportByName(null, "_ZN8universe7network8Packer3211packMessageEPNS0_9ZhouLuJunE");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                var m = ptr(a[1]);
                this.pid = m.add(0x10).readU32();
                this.aid = m.add(0x14).readU32();
                this.mid = m.add(0x18).readU32();
                this.plen = m.add(0x20).readU32();
                this.pl = toHex(m.add(0x30), this.plen);
            },
            onLeave: function(ret) {
                log({type:"packMsg", pid:this.pid, appid:this.aid, msgid:this.mid, paylen:this.plen, payload:this.pl, ts:Date.now()});
            }
        });
        send("[hook] packMessage");
    }

    // 6. connect
    p = Module.findExportByName(null, "_ZN8universe7network10GuoPengFei7connectEiNSt6__ndk112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEERKS8_i");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                var host = a[2].readCString();
                var ip = a[3].readCString();
                var port = a[4].toInt32();
                send("[connect] " + host + ":" + port);
                log({type:"connect", host:host, ip:ip, port:port, ts:Date.now()});
            }
        });
        send("[hook] connect");
    }

    // 7. uv_write — capture actual wire bytes
    p = Module.findExportByName(null, "uv_write");
    if (p) {
        Interceptor.attach(p, {
            onEnter: function(a) {
                var nb = a[3].toInt32();
                if (nb <= 0 || nb > 10) return;
                var bufs = ptr(a[2]);
                for (var i=0; i<nb; i++) {
                    var base = bufs.add(i*0x10).readPointer();
                    var blen = bufs.add(i*0x10+8).readU64();
                    if (blen > 0 && blen < 65536) {
                        log({type:"wire_send", i:i, len:parseInt(blen), data:toHex(base,parseInt(blen)), ts:Date.now()});
                    }
                }
            }
        });
        send("[hook] uv_write");
    }

    // 8. recv — capture incoming data
    var recv = Module.findExportByName("libc.so", "recv");
    var connect_libc = Module.findExportByName("libc.so", "connect");
    var fdMap = {};

    if (connect_libc) {
        Interceptor.attach(connect_libc, {
            onEnter: function(a) {
                this.fd = a[0].toInt32();
                this.addr = a[1];
            },
            onLeave: function(r) {
                if (r.toInt32() === 0) {
                    var p = (this.addr.add(2).readU8()<<8)|this.addr.add(3).readU8();
                    var ip = this.addr.add(4).readU8()+"."+this.addr.add(5).readU8()+"."+this.addr.add(6).readU8()+"."+this.addr.add(7).readU8();
                    fdMap[this.fd] = ip+":"+p;
                    log({type:"tcp_conn", fd:this.fd, addr:fdMap[this.fd], ts:Date.now()});
                }
            }
        });
        send("[hook] libc connect");
    }

    if (recv) {
        Interceptor.attach(recv, {
            onEnter: function(a) {
                this.fd = a[0].toInt32();
                this.buf = a[1];
            },
            onLeave: function(r) {
                var n = r.toInt32();
                if (n <= 0 || n > 65536) return;
                var addr = fdMap[this.fd];
                if (addr) {
                    log({type:"tcp_recv", len:n, remote:addr, data:toHex(this.buf,n), ts:Date.now()});
                }
            }
        });
        send("[hook] recv");
    }

    HIT = true;
    send("[init] All native hooks installed!");
}

// Try immediately, and retry every 2 seconds
installAllHooks();
var retryCount = 0;
var timer = setInterval(function() {
    if (HIT) { clearInterval(timer); return; }
    installAllHooks();
    retryCount++;
    if (retryCount > 30) { clearInterval(timer); send("[init] Gave up after 30 retries"); }
}, 2000);

send("[init] Waiting for libcocos2dlua.so to load... output: " + OUTPUT);
