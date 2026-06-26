// List all modules visible to Frida
var mods = Process.enumerateModules();
console.log("Total modules: " + mods.length);
var interesting = [];
for (var i = 0; i < mods.length; i++) {
    var n = mods[i].name;
    if (n.indexOf("cocos") >= 0 || n.indexOf("nb") >= 0 || n.indexOf("ndk") >= 0 || n.indexOf("arm") >= 0 || n.indexOf("translate") >= 0) {
        interesting.push(n + " (" + mods[i].base + " size:" + mods[i].size + ")");
    }
}
console.log("Interesting modules: " + interesting.length);
for (var j = 0; j < interesting.length; j++) {
    console.log("  " + interesting[j]);
}
// Check if we can hook a libc-level function to capture network traffic
var connect = Module.findGlobalExportByName("connect");
var send = Module.findGlobalExportByName("send");
var recv = Module.findGlobalExportByName("recv");
console.log("libc connect: " + (connect ? "OK" : "FAIL"));
console.log("libc send: " + (send ? "OK" : "FAIL"));
console.log("libc recv: " + (recv ? "OK" : "FAIL"));
