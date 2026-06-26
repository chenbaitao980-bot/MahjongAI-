console.log("Module keys: " + Object.keys(Module).join(", "));
console.log("=== trying Module.getExportByName ===");
try {
    var r = Module.getExportByName("libc.so", "recv");
    console.log("getExportByName libc recv: " + r);
} catch(e) { console.log("getExportByName error: " + e); }

console.log("=== trying Process.getModuleByName ===");
try {
    var libc = Process.getModuleByName("libc.so");
    console.log("libc.so base: " + libc.base);
    console.log("libc exports count: " + libc.enumerateExports().length);
} catch(e) { console.log("Process error: " + e); }

console.log("=== trying Process.findModuleByAddress ===");
try {
    console.log("ok");
} catch(e) { console.log("error: " + e); }
