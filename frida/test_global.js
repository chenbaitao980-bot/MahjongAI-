console.log("=== findGlobalExportByName ===");
try {
    var r = Module.findGlobalExportByName("recv");
    console.log("recv: " + r);
} catch(e) { console.log("error: " + e); }

console.log("=== getGlobalExportByName ===");
try {
    var r = Module.getGlobalExportByName("recv");
    console.log("recv: " + r);
} catch(e) { console.log("error: " + e); }

// Test the C++ symbol
var libcocos = Process.getModuleByName("libcocos2dlua.so");
console.log("libcocos2dlua.so base: " + libcocos.base + " size: " + libcocos.size);
// Enumerate a few exports to see the naming pattern
var exports = libcocos.enumerateExports();
var srsExports = [];
for (var i = 0; i < exports.length; i++) {
    if (exports[i].name.indexOf("encrypt") >= 0 || exports[i].name.indexOf("setAes") >= 0 || exports[i].name.indexOf("GuoPeng") >= 0) {
        srsExports.push(exports[i].name + " @ " + exports[i].address);
    }
}
console.log("SRS-related exports: " + srsExports.length);
for (var j = 0; j < Math.min(srsExports.length, 10); j++) {
    console.log("  " + srsExports[j]);
}
