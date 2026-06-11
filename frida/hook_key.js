/**
 * SRS Key Derivation Hook — minimal script
 * 
 * Hooks the exact functions that handle RespKey → AES key derivation.
 * Run on real ARM64 Android phone with frida-server.
 * 
 * Setup:
 *   1. Download frida-server-17.9.10-android-arm64.xz from GitHub
 *   2. Extract and push to phone: adb push frida-server /data/local/tmp/
 *   3. adb shell "su -c 'chmod 755 /data/local/tmp/frida-server && /data/local/tmp/frida-server -D &'"
 *   4. Run: frida -U -f com.xm.zjgamecenter -l hook_key.js --no-pause
 */

// ===== 1. Hook Encryption::setAesKey(key, len) =====
// Captures the final AES key after RespKey parsing
var setAesKey = Module.findExportByName(null, "_ZN8universe7network10Encryption9setAesKeyEPKhm");
if (setAesKey) {
    Interceptor.attach(setAesKey, {
        onEnter(args) {
            var keyLen = args[2].toInt32();
            var keyHex = hexdump(args[1], {length: keyLen, ansi: false});
            console.log("\n[setAesKey] key_len=" + keyLen);
            console.log(keyHex);
            
            // Also log as single hex string for easy copy
            var bytes = args[1].readByteArray(keyLen);
            var hex = Array.from(new Uint8Array(bytes))
                .map(b => ("0"+b.toString(16)).slice(-2)).join("");
            console.log("[setAesKey] HEX_KEY=" + hex);
        }
    });
    console.log("[+] setAesKey hooked");
} else {
    console.log("[-] setAesKey NOT FOUND");
}

// ===== 2. Hook GuoPengFei::setAesKey(key, len) =====
var setAesKey2 = Module.findExportByName(null, "_ZN8universe7network10GuoPengFei9setAesKeyEPKcm");
if (setAesKey2) {
    Interceptor.attach(setAesKey2, {
        onEnter(args) {
            var keyLen = args[2].toInt32();
            var bytes = args[1].readByteArray(keyLen);
            var hex = Array.from(new Uint8Array(bytes))
                .map(b => ("0"+b.toString(16)).slice(-2)).join("");
            console.log("\n[GuoPengFei.setAesKey] len=" + keyLen + " key=" + hex);
        }
    });
    console.log("[+] GuoPengFei.setAesKey hooked");
} else {
    console.log("[-] GuoPengFei.setAesKey NOT FOUND");
}

// ===== 3. Hook Encryption::encrypt — see what gets encrypted =====
var encryptFn = Module.findExportByName(null, "_ZN8universe7network10Encryption7encryptEPKhPhmS3_Pi");
if (encryptFn) {
    Interceptor.attach(encryptFn, {
        onEnter(args) {
            this.plaintext = args[1];
            this.plainLen = args[3].toInt32();
            this.ivPtr = args[4];
        },
        onLeave(retval) {
            console.log("\n[encrypt] plain_len=" + this.plainLen);
            console.log("  plaintext: " + hexdump(this.plaintext, {length: Math.min(this.plainLen, 64), ansi: false}));
            if (this.ivPtr && !this.ivPtr.isNull()) {
                console.log("  IV: " + hexdump(this.ivPtr, {length: 16, ansi: false}));
            }
        }
    });
    console.log("[+] encrypt hooked");
} else {
    console.log("[-] encrypt NOT FOUND");
}

// ===== 4. Hook GuoPengFei::onRespKey =====
var onRespKey = Module.findExportByName(null, "_ZN8universe7network10GuoPengFei9onRespKeyEPNS0_9ZhouLuJunE");
if (onRespKey) {
    Interceptor.attach(onRespKey, {
        onEnter(args) {
            // args[1] = ZhouLuJun* (the RespKey message)
            var msg = ptr(args[1]);
            var pid = msg.add(0x10).readU32();
            var aid = msg.add(0x14).readU32();
            var mid = msg.add(0x18).readU32();
            var plen = msg.add(0x20).readU32();
            console.log("\n[onRespKey] processid=" + pid + " appid=" + aid + " msgid=" + mid + " payload_len=" + plen);
            
            if (plen > 0 && plen < 256) {
                console.log("  payload: " + hexdump(msg.add(0x30), {length: plen, ansi: false}));
            }
        }
    });
    console.log("[+] onRespKey hooked");
} else {
    console.log("[-] onRespKey NOT FOUND");
}

// ===== 5. Hook Encryption::transformStr — see input/output =====
var transformStr = Module.findExportByName(null, "_ZN8universe7network10Encryption12transformStrEPKhmPPhPm");
if (transformStr) {
    Interceptor.attach(transformStr, {
        onEnter(args) {
            this.inLen = args[2].toInt32();
            this.inPtr = args[1];
            this.outPtrPtr = args[3];
            this.outLenPtr = args[4];
        },
        onLeave(retval) {
            var outPtr = this.outPtrPtr.readPointer();
            var outLen = this.outLenPtr.readU64();
            console.log("\n[transformStr] in_len=" + this.inLen + " out_len=" + outLen);
            if (this.inLen > 0) {
                console.log("  input:  " + hexdump(this.inPtr, {length: Math.min(this.inLen, 32), ansi: false}));
            }
            if (outLen > 0) {
                console.log("  output: " + hexdump(outPtr, {length: Math.min(parseInt(outLen), 64), ansi: false}));
            }
        }
    });
    console.log("[+] transformStr hooked");
} else {
    console.log("[-] transformStr NOT FOUND");
}

console.log("\n===== All hooks installed =====");
console.log("Open the game and watch for [setAesKey] output.");
console.log("The HEX_KEY is what we need for Python implementation.");
