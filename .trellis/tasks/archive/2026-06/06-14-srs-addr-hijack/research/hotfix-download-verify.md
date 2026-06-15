# 热更下载 / 校验链路逆向结论（决定 manifest_forge 喂什么字节、md5 怎么算）

来源：`apk_research/decrypted-lua/app/hotupdate/universe/hotfix/{HotFixProcessor,Manifest,ZipDownloader,DiffList,DeferMerge,Compat,init}.lua` +
`app/hotupdate/lobby/ResChecker.lua` + 真实 manifest `apk/game_base.apk!assets/res/GameHotUpdate3/Lobby/project_10001.manifest`（148KB，915 条）。

## 0. 三个 manifest 的关系（必看）

热更里有**三个** Manifest 对象（`Manifest.lua`）：

| 名称 | 来源 | 作用 |
|------|------|------|
| `localManifest` | APK 内 `GameHotUpdate3/Lobby/project_10001.manifest` + 热更目录里已存的 `project.manifest` | 本地基线（版本+file_list） |
| `versionManifest` | `update_url` GET 回来的小 **version.manifest** | 只看 `version` 决定是否要更新；含 `manifest_url`、`project_md5` |
| `projectManifest` | `versionManifest:getManifestUrl()` GET 回来的**完整 project.manifest** | 真正的 file_list，diff 的对端 |

流程（`HotFixProcessor:start` → `_onVersionDownload` → `update` → `_downloadProjectManifest` → `_onProjectDownload` → `_generalDownload` → `_startMerge`）：

1. **GET version.manifest**：`d2.add(fullUrl, versionPath, "", ...)`（md5 空 = 不校验）。URL = `update_url[i]`（已含 `?...&version=<本地版本>`）经 `un.url.generate` 拼 `ip/os/hardware/res_status` 参数。下载器 = `un.downloader2`。
2. 比较版本：`checkVersionUpdate(parseVersion(old), parseVersion(new))` —— **逐段数字 `<` 比较**（段1<段1 或 段2<段2 …）。只要 version.manifest 的 version > 本地，就判定需更新。`Manifest.__lt`/`versionLessThan` 同理（按 `%d+` 提取数字段逐段比）。
3. **GET project.manifest**：`url = versionManifest:getManifestUrl()`，`md5 = versionManifest:getProjectMd5()`。`d2.add(url, projectTempPath, md5, ...)` —— **若 version.manifest 给了 project_md5，会校验 project.manifest 字节的 md5**。
4. `genDiffList(projectManifest)`：遍历 **local** 的 file_list，对每个 key 取 project 同名条目，`projectFile.md5 ~= localFile.md5` → 加入 diff（MODIFY），`name/zipMd5` 取 **project 的**，`size` 取 **local 的**。project 里 local 没有的 key → ADD。local 有 project 没有的 → DELETE。
5. **下载文件**：`d2.add(curUrl .. info.name .. suffix, downloadPath .. file, info.zipMd5, ...)`。
   - `curUrl` = `projectManifest:getFileUrl()[i]`（= `file_url`，如 `https://gxb-oss.hzxuanming.com/yj/files/`）。
   - `info.name` = project manifest 里该文件的 `name`（= `xx/<sha1>.<ext>`）。
   - `info.zipMd5` = project manifest 里该文件的 `md5` → **下载器按此 md5 校验下载到的字节**。
   - `suffix = "?rand=" .. os.clock()`（防缓存，无害）。
6. **合并**（`startDecompress` → `_startMerge`）：通用路径 **直接 `fs.renameFile(downloadPath .. file, rootPath .. file)`**，把下载文件原样改名进 `rootPath = getWritePath() .. HotFixPath`。**没有任何解压/gunzip**。

## 1. version-manifest 用什么下载器？验证证书吗？——走 Downloader2（验证关），安全

- `HotFixProcessor:start()` 里 version.manifest、project.manifest、各文件**全部用 `un.downloader2`（`d2`）**，即 native `universe::Downloader2`（反汇编实锤 `VERIFYPEER=0`+`VERIFYHOST=0`），**接受自签证书**。
- `un.Http` 只在 **`HotFixProcessor:_report()`（埋点上报 monitor_url）** 用到，不在主下载链路。`_report` 失败只打印日志、重试 3 次，**不阻断热更**。
- `Compat.lua` 有个 `un.downloader2` 的纯 Lua 兜底实现（用 `un.Downloader.new()` 包一层），但真机有 native `Downloader2` 时不会走兜底。**风险点**：若某些机型 native 没注册 `un.downloader2`，会落回 `un.Downloader`（cocos `Downloader`）——它是否验证证书未在 Lua 层确定。**需真机/抓包确认 native Downloader2 在目标机生效**（PRD M0 已列为必测）。

> 结论：主链路确认走验证关的 Downloader2，自签证书可被接受。`un.Http` 仅埋点旁路，不影响。

## 2. file_list 的 md5 是对什么字节算的？——对 CDN 在 `name` 路径**原样返回的字节**算

- 下载器校验 `info.zipMd5`（= project manifest 的 `md5`）对**下载到的原始字节**。
- 合并阶段**原样改名**进 `rootPath`，**无 gunzip/unzip**（通用路径）。
- 因此：CDN 在 `file_url + name`（如 `…/yj/files/12/1268bd….luac`）返回的字节 = 最终落盘的 `src/app/config/NetConf.luac` 字节 = 游戏直接 XXTEA 解的 luac（`SIGN + XXTEA(src)`）。
- **所以 `md5` = md5(最终 luac 字节)。我们要投递改过的 NetConf.luac，则 file_list 里填 `md5 = md5(改过的 luac bytes)`、`size = len(改过的 luac bytes)`。**（`manifest_forge` 即按此实现。）

> 旁证：APK 内置 `Config/NetConf.luac` 是 13485 字节 md5=`c24ded8f…`，而真实 manifest 条目是 `size=6753, md5=473fa0ff…, name=12/1268bd….luac` —— 两者不同，说明**线上 CDN 已是更新过的、更小的 luac**（与内置不同版本），但都是「原样 luac、md5 对原始字节」这一规则，没有压缩层。压缩只在 **zip 路径**（diff_zip / zip_url）出现，我们用 `forbid_zip` 关掉它（见 §3）。

**仍需真机确认**：极个别引擎可能在 `name` 后缀为 `.gz`/`.zip` 时另走 `un.Decompressor`（`HotFixProcessor:startDecompress` 里被注释掉的旧逻辑用过 `un.Decompressor`）。真实 manifest 里 NetConf 的 `name` 后缀是 `.luac`、通用路径不解压，所以判定为「直接 luac」。**若真机抓包发现 CDN 对 .luac 返回 gzip 且引擎确实 gunzip，则 manifest_forge 的 md5 需改成对 gzip 字节算、setup_mitm 改为 serve gzip。**（代码注释已标）

## 3. zip / diff 路径如何规避（保证只下 NetConf 一个文件）

`HotFixProcessor:update()` 选下载方式的顺序：

1. `canUseZip = not localManifest:isForbidZip()`（读 `forbid_zip`）。
2. 若 `canUseZip` 且 **version.manifest** 有 `diff_zip.url`（`getZipList`）→ 走 zip 差分包。
3. 若 `canUseZip` 且缺文件且 `getFoundFileCount() < 8` 且有 `zip_url`（`getFullZipList`）→ 走整包 zip。
4. 否则 → `_startGeneralDownload`（**逐文件下载，无压缩，正是我们要的**）。

**规避手段（manifest_forge 写进伪 manifest）**：
- `forbid_zip = true` 写进 **project manifest（= localManifest 更新后比对用的、以及 isForbidZip 读的 local）**。注意 `isForbidZip` 读的是 **localManifest**；首次热更时 `loadManifest` 会把 APK 内 manifest 当 local 存盘，所以最稳的是**让我们 serve 的 project.manifest 带 `forbid_zip=true`**，并且**不带 `diff_zip` / `zip_url`**。version.manifest 也不带 `diff_zip`/`zip_url`。这样 §2/§3 的 zip 分支因 `zipList==nil` 直接跳过 → 必走 general。
- general diff：只有 NetConf 的 md5 与本地不同 → diff 只剩 NetConf 一条 → 只下一个文件。其余 914 条 name/md5/size 原样保留 = 与本地一致 = 不进 diff。

> `genDiffList` 还有个 `elseif not layerFS.isFileExist(k)` 分支：md5 相同但**本地物理文件缺失**会触发 ADD（重下）。首次热更、纯净安装时 APK 里这些资源是存在的（layerFS 含 APK 层），一般不缺。**最坏情况**：若某些文件在可写层确实缺失，会多下几个文件——不影响 NetConf 注入正确性，只是流量大些。**需真机确认首包 isHaveMissingFile**（`res_status` 参数即反映此，`start()` 里 `isHaveMissingFile` 会影响是否走 full zip；我们 `forbid_zip` 已挡住）。

## 4. `name` 路径规则

`name = "<sha1 前 2 hex>/<sha1 40hex>.<原扩展名>"`，完整 URL = `file_url[i] + name`（无额外目录）。例：
`https://gxb-oss.hzxuanming.com/yj/files/12/1268bdb0428b6669b836e5419a73eaadd5534809.luac`。
我们投递的 NetConf 可复用原 name（路径任意，只要 setup_mitm 的 HTTP server 在该路径返回我们的字节即可），或换成 `md5(served)` 派生的新 name。`manifest_forge` 采用「`name = <md5前2>/<md5全>.luac`」便于 server 路由（md5 已知、自洽）。

## 5. version.manifest 要伪造哪些字段

`_onVersionDownload` + `_downloadProjectManifest` 实际读：`version`（顶高）、`manifest_url`（指向我们 project.manifest）、`project_md5`（= md5(我们 project.manifest 字节)，可填空串""跳过校验，d2 对空 md5 不校验）、可选 `update_type`/`tip_msg`。**不要**带 `diff_zip`/`zip_url`。

setup_mitm 的 `/hotfix_update`（= update_url）返回此 version.manifest；其 `manifest_url` 指我们自己的项目 manifest 路径；该路径返回 `manifest_forge` 的完整伪 project.manifest。

## 6. 一句话给下游模块

- **manifest_forge**：克隆真实 project.manifest，`version` 顶高、`forbid_zip=true`、删 `diff_zip`/`zip_url`（真实里本就没有），只改 NetConf 一条的 `md5=md5(served)`、`size=len(served)`、`name=<md5派生>.luac`，其余 914 条原样。md5 对**原始 luac 字节**算。
- **setup_mitm**：`/hotfix_update`→伪 version.manifest（高版本 + manifest_url/file_url 指向自己）；项目 manifest 路径→伪 project.manifest；`file_url + name`→改过的 NetConf.luac 原始字节。全程自签 TLS（VERIFYPEER=0 接受）。
- **md5/gzip 唯一未 100% 确定点**：CDN 对 `.luac` 是否返回 gzip 且引擎 gunzip。逆向判定「否」（通用路径无解压），但**需真机抓一次包确认**；若为是，改 md5 算法与 serve 字节为 gzip。
