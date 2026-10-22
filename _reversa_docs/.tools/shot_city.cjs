const path=require("path");const {chromium}=require(process.argv[2]);
(async()=>{const b=await chromium.launch({args:["--use-gl=swiftshader","--enable-webgl","--ignore-gpu-blocklist"]});
const p=await b.newPage({viewport:{width:1400,height:1000}});
await p.goto("file://"+path.resolve(__dirname,"../arquitetura.html"));await p.waitForTimeout(2500);
await (await p.$(".layout-side")).screenshot({path:path.resolve(__dirname,"../.logs/shots/city.png")});await b.close();})();
