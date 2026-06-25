# brainstorm: 用官方牌面与财神特效替换 AI 图

## Goal

之前「卡牌显示牌面」任务用 AI 生成的 34 张麻将 PNG 渲染 web 后台手牌。既然 app 已被反编译/热更资源链路已打通，目标是**直接复用浙江游戏大厅官方的麻将牌面（以及可能的财神特效）**，让后台读牌界面与真实游戏视觉一致。

## What I already know

* 当前渲染载体 = web 后台（`remote/relay/static/index.html` + `static/tiles/*.png`），noconfig 远程读牌网页，commit afbd210「后台手牌改用 AI 麻将图片渲染」。
* 桌面 PyQt 面板（`ui/battle_panel.py` / `ui/stable_battle_panel.py`）目前仍是纯文字（`TILE_NAME_MAP`），无图。
* 官方牌面 = Cocos Studio 资源（`res/cocosStudio/MahjongNew/...`），plist 图集形态，存在热更服务器 `gxb-oss.imeete.com` / `hzxuanming.com`。
* APK 内仅有 manifest（`assets/res/GameHotUpdate3/Mahjong/`、`MahFace/7101-7136`、`Ani/project_MahjongAni.manifest`），且 `file_list` 为空 → 真实文件清单需现连热更服务器拉取。
* 牌面有**多套地区皮肤**：MahFace 7101–7136，部分地区共用（如青田=丽水、嘉兴=余姚）。
* 财神特效 = Cocos 骨骼动画（`Config.lua`: `AniPicName="caishen.png"`, `FileName="qf_caishen01"`, `ArmatureName`, `ArriveMusicName="gongxifacai.mp3"`），**非单张图**。
* 历史记忆：热更 MITM 已验证可下全量资源（16495 文件，下到手机/ECS 缓存），但**未存到本地 PC**。

## Decisions (locked)

* **范围**：只换牌面静图。财神特效维持现状（web 端红框标记 `.caishen`），不做骨骼动画。
* **资源获取**：现连热更服务器抓取+解包（已验证公网 curl 直接可下，无需 MITM）。
* **皮肤**：固定用**台州麻将**那套 → MahFace **areaid 7109**（`GlobalDefine.lua:169`，独立套，不与他区共用）。
* **载体**：web 后台 noconfig 网页（`remote/relay/static/`），替换 `static/tiles/*.png`。

## Verified Feasibility (research done)

* 7109 牌面 = 单个 Cocos plist 图集 `mahlayer_mah_face_2.plist` + `.png`（1024×1024，1.12MB）。
* 热更链路：`GET https://gxb-api.imeete.com/hotfix_update?env=1&appid=1233&engine_ver=3.13&channel=7109&version=1.0.0.0` → 返回 manifest_url → manifest 的 `file_list` 给出真实存储名（md5 分桶）→ `GET file_url + name` 下载。
* 切图脚本已跑通：plist 43 帧，`rotated:true` 需 `rotate(-90,expand)` 还原 → **34 张牌面全部产出，统一 140×158**，像素验证为真实牌面（已存 `research/sample_7109/out/`）。
* 帧编码 = nibble：`0x11-0x19`=1-9m、`0x21-0x29`=1-9p、`0x31-0x39`=1-9s、`0x41-0x44`=东南西北(1-4z)、`0x51-0x53`=中发白(5-7z)。
* 现有 web 渲染 `tileEl()` 已是 `<img src="tiles/{n}{suit}.png">`，**只需替换图片文件，前端代码零改动**。

## Requirements

* 新增可复跑脚本 `scripts/fetch_official_tiles.py`：拉 7109 manifest → 下载 plist+png → 按 nibble 映射切成 34 张 `{tile}.png` → 输出到 `remote/relay/static/tiles/`。
* 切图保留透明通道；命名与现有一致（`1m.png`…`7z.png`）。
* 脚本记录来源 URL + md5 校验，失败可重试（oss/cos 双源）。
* 替换 `remote/relay/static/tiles/` 下 34 张 AI PNG 为官方台州牌面。

## Acceptance Criteria

* [x] `python scripts/fetch_official_tiles.py` 一键产出 34 张官方台州牌面到 `static/tiles/`。
* [x] web 后台读牌网页手牌/弃牌/碰杠用官方牌面渲染，视觉与真机台州麻将一致（`tileEl()` 引用 `tiles/{n}{suit}.png`，34 张文件名全部就位，零代码改动）。
* [x] 财神红框（`.caishen`）仍正常标记（前端逻辑未动）。
* [x] 万/筒/条/字映射全部正确（nibble 帧号 hi=1万/2筒/3条/4风/5箭，切出 34 张与研究验证产物逐字节一致）。

## Definition of Done (team quality bar)

* 资源抓取脚本可复跑（记录来源 URL + 校验）。
* 牌面 tile_id → 图片映射正确（条→万→筒→字 instance 顺序坑）。
* Docs/部署说明更新（资源体积、放置路径）。

## Out of Scope (explicit)

* 桌面 PyQt 牌面图渲染（除非确认要）。

## Spec Conflicts

* 暂未发现 spec 硬冲突（待 Step 1 spec 扫描确认）。

## Technical Notes

* 牌面资源路径锚点：`apk_research/decrypted-lua/app/Config/GameSub.lua` SearchPath = `res/cocosStudio/MahjongNew/...`。
* 财神配置：`apk_research/decrypted-lua/app/Config/prop/Config.lua:25,32`。
* MahFace 皮肤映射：`apk_research/decrypted-lua/app/hotupdate/mahface/MahFaceHotUpdateData.lua`。
* 热更下载/MITM 链路：`remote/noconfig/hijack/`（manifest_forge.py / setup_mitm.py / netconf_patch.py）。
