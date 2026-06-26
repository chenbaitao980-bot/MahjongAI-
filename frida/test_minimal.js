console.log("=== testing x86_64 emulator ===");
console.log("Arch: " + Process.arch);

// Test libc hooks (x86_64 native functions)
var recv = Module.findExportByName("libc.so", "recv");
console.log("libc recv: " + (recv ? "FOUND at " + recv : "NOT FOUND"));

var send = Module.findExportByName("libc.so", "send");
console.log("libc send: " + (send ? "FOUND at " + send : "NOT FOUND"));

// Test the C++ mangled names from libcocos2dlua.so
var sym = Module.findExportByName(null, "_ZN8universe7network10Encryption9setAesKeyEPKhm");
console.log("setAesKey: " + (sym ? "FOUND at " + sym : "NOT FOUND"));

// List loaded modules
var mods = Process.enumerateModules();
for (var i = 0; i < mods.length; i++) {
    if (mods[i].name.indexOf("cocos") >= 0 || mods[i].name.indexOf("nb.") >= 0) {
        console.log("Module: " + mods[i].name + " base: " + mods[i].base + " size: " + mods[i].size);
    }
}
