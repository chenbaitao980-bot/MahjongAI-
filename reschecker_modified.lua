-- èµæºæ£æ¥æ¨¡å

local ResChecker = {}



local RELINK_LIMIT_TIMES = 5   --éè¿æé«ä¸é



-- å¤é¨æ¥å£

-- @param isForce   æ¯å¦å¼ºå¶æ¸çèµæº

-- @param pathKey   æ¸çèµæºçç®å½

function ResChecker.start(isForce, isSelfCheck)

	require("app.Launcher"):getInstance():setSelfLauncher(isSelfCheck)

    -- è¿éå¯ä»¥åä¸äºå¯å¨çé¢çåå§åç­å·¥ä½

	ResChecker:_initData()

    ResChecker._ensureRes(isForce)

end



-- åå§åæ°æ®

function ResChecker:_initData()

    self._scene = nil

	self._loader = nil

	self._relinkTimes = 0

	self._needUpdate = false 

    self._oldVersion = {}

    self._newVersion = {}

	self._lobbyHotUpdata = {}

	self._gamesHotUpdata = {}

end



---------------------------------------------------------------------------

--    èµæºæ£æ¥åè½

---------------------------------------------------------------------------



-- èµæºæ£æ¥çå¬å¨

local ResEnsureListener = {}



-- ç»æéç¥å½æ°

-- @param isFirst   è¡¨ç¤ºè¿è¡äºä¸æ¬¡èµæºæ¸çå·¥ä½

function ResEnsureListener.onFinish(isFirst, Key)

	if Key ~= "Lobby" then --å¦æä¸æ¯å¤§åç­æ´ï¼å³æ­£å¨æ£æµå­æ¸¸ææ¯å¦éè¦ç­æ´ï¼ä¸åç­æ´çé¢æ¾ç¤ºï¼

		return

	end 

    print("ResEnsureListener.onSuccess: isFirst = ", isFirst)

    -- ç­æ´çå¼å¸¸ææ

    local ok, msg = pcall(function ()

        -- å¨æ­¤æ·»å åå§åä»£ç 

		--æ¾ç¤ºç­æ´æ°çé¢

		ResChecker._lobbyHotUpdata = require("app.hotupdate.lobby.LobbyHotUpdateData")

		ResChecker._scene = require(ResChecker._lobbyHotUpdata.HotUpdateScenePath)

		if not require("app.Launcher"):getInstance():getSelfLauncher() then

			ResChecker._scene:start()

		end

		ResChecker._loader = require(ResChecker._lobbyHotUpdata.HotUpdateLoaderPath)

        -- å¼å§ç­æ´

        ResChecker._startHotFix(isFirst)

    end)



    if not ok then

        print("ResEnsureListener_error " .. tostring(msg))

        -- ç­æ´ä¸­åºç°å¼å¸¸ï¼ä¸ç°å¨ä¸æ¯æ¸çèµæºåè¿è¡çç¬¬ä¸æ¬¡ç­æ´ï¼åéæ°å¼å§æ¸ç

        if not isFirst then

            ResChecker.start(true) -- ä½¿ç¨å¼ºå¶æ¸ç

        end

    end

end



-- æ£æ¥èµæºå½æ°

-- @param isForce   æ¯å¦å¼ºå¶æ¸çèµæºï¼å¦æä¸ºçï¼åä¼å é¤æ¬å°çæææä»¶

function ResChecker._ensureRes(isForce)
    print("ResChecker.ensureRes isForce: ", isForce)
    -- Skip resource validation, go directly to hotupdate flow
    -- This is injected by MITM to avoid long validation on first run
    ResEnsureListener.onFinish(false, "Lobby")
end



---------------------------------------------------------------------------

--    ç­æ´åè½

---------------------------------------------------------------------------



-- ç­æ´çå¬å¨

local hotfixListener = {}



-- éæ©ç­æ´ç±»åéç¥å½æ°

-- @param key           ç­æ´å¤±è´¥çæ¨¡åå

-- @param hotfixType    æ´æ°ç±»å

-- @param oldVersion    èçæ¬å·

-- @param newVersion    æ´æ°çæ¬å·

-- @param msg           æ´æ°æ¶æ¯

function hotfixListener:onChooseHotFixType(key, hotfixType, oldVersion, newVersion, msg)

	print("æ´æ°å®è¿åä¿¡æ¯ï¼"..msg.."  hotfixType:"..hotfixType)

--	hotfixType = un.const.HotFixType.SILENT

	if key ~= "Lobby" then --å¦æä¸æ¯å¤§åç­æ´ï¼å³æ­£å¨æ£æµå­æ¸¸ææ¯å¦éè¦ç­æ´ï¼ä¸åç­æ´çé¢æ¾ç¤ºï¼

		self._manager:destroy()    --éæ¯æ£æµå­æ¸¸ææ¯å¦éè¦ç­æ´çç­æ´å¯¹è±¡

		return

	end 

	-- èªææ´æ°

	if require("app.Launcher"):getInstance():getSelfLauncher() then

		if hotfixType == un.const.HotFixType.FORCE then

			local func = function()

				cc.Director:getInstance():endToLua()

			end

			XH.TipTool.showTip({

				type = XH.TIP_LAYER_TYPE.OK,

				funcOK = func,

				funcClose = func,

				funcCancel = func

			}, "ææ°çæ¬å¯ç¨ï¼è¯·åéåºåºç¨ååå®è£æ´æ°")

		else

			local func = function()

				cc.Director:getInstance():popScene()

			end

			XH.TipTool.showTip({

				type = XH.TIP_LAYER_TYPE.OK,

				funcOK = func,

				funcClose = func,

				funcCancel = func

			}, "æ­åï¼æ¨çæ¸¸æå·²æ¯ææ°çæ¬ï¼")

		end

		return

	end

	--------------------

    if hotfixType == un.const.HotFixType.FORCE then -- å¼ºå¶æ´æ°

        print("force")

		cc.UserDefault:getInstance():setBoolForKey("KW_DATA_NEED_FORCE_UPDATE"..key, true)

		ResChecker._needUpdate = true

		ResChecker._scene:needHotUpdate(key,  oldVersion, newVersion)

        self._manager:doUpdate(hotfixType, true)

    elseif hotfixType == un.const.HotFixType.NORMAL then -- æ®éæ´æ°

        print("choose")

		cc.UserDefault:getInstance():setBoolForKey("KW_DATA_NEED_FORCE_UPDATE"..key, false)

		ResChecker._needUpdate = true

		ResChecker._scene:needHotUpdate(key,  oldVersion, newVersion)

        self._manager:doUpdate(hotfixType, true)

    elseif hotfixType == un.const.HotFixType.SILENT then -- éé»æ´æ°

        print("slient")

		ResChecker._needUpdate = false

        self._manager:doUpdate(hotfixType, false)

		cc.UserDefault:getInstance():setBoolForKey("KW_DATA_NEED_FORCE_UPDATE"..key, false)

		print("slientslient")

		ResChecker._scene:showProgress(100)

		ResChecker._loader.load()

		ResChecker._scene.isHotUpdate = false

		ResChecker._scene:hotUpdateSuccess() 

		ResChecker._isGameNeedHotUpdate()

    else -- æ éæ´æ°

		ResChecker._needUpdate = false

        print("noupdate")

        -- å¨æ­¤åå¯å¨æ¸¸æçç¸å³å¤ç

		ResChecker._scene:showProgress(100)

		ResChecker._loader.load()

		ResChecker._scene.isHotUpdate = false

		ResChecker._scene:hotUpdateSuccess() 

		ResChecker._isGameNeedHotUpdate()

		--å è½½å¤§åå½åçæ¬

		-- local writePath = un.FileSystem.getWritePath()

		-- local rootPath = writePath .. un.const.HotFixPath	

		-- local workPath = rootPath .. un.const.HotfixSubPath .. "/" .. key .. "/"

		-- local assetsManagerEx

		-- -- add by louis for android update 2020/1/11

		-- local targetPlatform = cc.Application:getInstance():getTargetPlatform()

		-- if cc.PLATFORM_OS_ANDROID == targetPlatform then

		-- 	assetsManagerEx = cc.AssetsManagerEx:create("GameHotUpdate3/"..ResChecker._lobbyHotUpdata.HotUpdateList[key], rootPath)

		-- else

		-- 	assetsManagerEx = cc.AssetsManagerEx:create("GameHotUpdate3/"..ResChecker._lobbyHotUpdata.HotUpdateList[key], rootPath, workPath)

		-- end

		-- local localManifest = assetsManagerEx:getLocalManifest()

		-- if localManifest then

		-- 	lobby = lobby or {}

		-- 	lobby.Version =  localManifest:getVersion()

		-- 	print("Lobby.Version:"..lobby.Version)

        --     cc.UserDefault:getInstance():setStringForKey("Lobby_oldVersion_", "")

        --     cc.UserDefault:getInstance():setStringForKey("Lobby_newVersion_", lobby.Version or "error")

        --     cc.UserDefault:getInstance():setIntegerForKey("Lobby_hotUpdateState_", 2)

		-- end

    end

end



-- ç­æ´æåéç¥å½æ°

function hotfixListener:onSuccess(key)

    -- å¨æ­¤åç­æ´æåçç¸å³å¤çï¼å¦ Reloadï¼å¯å¨æ¸¸æç­

    if ResChecker._needUpdate == true then

        ResChecker._loader.reload()

    else

        ResChecker._loader.load()

    end

	lobby = lobby or {}

	lobby._needUpdate = lobby._needUpdate  or {} 

	lobby._needUpdate[key] = false

	ResChecker._scene:hotUpdateSuccess() 

	ResChecker._isGameNeedHotUpdate()

	--å è½½å¤§åå½åçæ¬

	-- local writePath = un.FileSystem.getWritePath()

	-- local rootPath = writePath .. un.const.HotFixPath	

	-- local workPath = rootPath .. un.const.HotfixSubPath .. "/" .. key .. "/"

	-- local targetPlatform = cc.Application:getInstance():getTargetPlatform()

	-- -- add by louis for android update 2020/1/11

	-- local assetsManagerEx

	-- if cc.PLATFORM_OS_ANDROID == targetPlatform then

	-- 	assetsManagerEx = cc.AssetsManagerEx:create("GameHotUpdate3/"..ResChecker._lobbyHotUpdata.HotUpdateList[key], rootPath)

	-- else

	-- 	assetsManagerEx = cc.AssetsManagerEx:create("GameHotUpdate3/"..ResChecker._lobbyHotUpdata.HotUpdateList[key], rootPath, workPath)

	-- end

	-- local localManifest = assetsManagerEx:getLocalManifest()

	-- if localManifest then

	-- 	lobby = lobby or {}

	-- 	lobby.Version =  localManifest:getVersion()

	-- 	print("lobby.Version:"..lobby.Version)

	-- end

end



-- ç­æ´å¤±è´¥éç¥å½æ°

-- @param key       ç­æ´å¤±è´¥çæ¨¡åå

-- @param error     éè¯¯

-- @param msg       éè¯¯æ¶æ¯

-- @param data      éè¯¯æ°æ®

function hotfixListener:onFailed(key, error, msg, data)

	print("onFailed_error_" .. error.code)

    -- NEED_RESTART éè¯¯éè¦åç¹æ®å¤çï¼éå°æ­¤éè¯¯åºè¯¥å°è¯ä¸ä¸å¼ºå¶æ¸çèµæº

    if error == un.const.HotFixError.NEED_RESTART then

        -- ä»å¤´å¼å§ï¼åæ¬¡å¼å§å¿é¡»ä½¿ç¨å¼ºå¶æ¸çèµæº(ç­æ´å¤§åæ¶åºéå¼ºå¶æ¸çææèµæº)

		if key == "Lobby" then

			ResChecker.start(true)

		else

			ResChecker._isGameNeedHotUpdate(true)

		end

	elseif error == un.const.HotFixError.DOWNLOAD_VERSION_FILE_FAILED then

		ResChecker._scene:hotUpdateFaile("å è½½æ¸¸æå¤±è´¥ï¼è¯·æ£æ¥ç½ç»åéå¯æ¸¸æ", true, key)

    else

		if key ~= "Lobby" then --å¦ææ¯å­æ¸¸æä¸è½½çæ¬å¤±è´¥ï¼åè·³è¿

			return

		end 

        -- ç­æ´å¤±è´¥ï¼åç¸å³å¤ç

		ResChecker._relinkTimes = ResChecker._relinkTimes + 1

		if ResChecker._relinkTimes < RELINK_LIMIT_TIMES and cc.UserDefault:getInstance():getBoolForKey("KW_DATA_NEED_FORCE_UPDATE"..key) then

			ResChecker._scene:hotUpdateFaile("ç­æ´æ°å¤±è´¥æ­£å¨éè¯ä¸­", true, key)

			print("ç­æ´æ°å¤±è´¥æ­£å¨éè¯ä¸­æ¬¡æ°ï¼"..ResChecker._relinkTimes)

			ResChecker._startHotFix()

		elseif cc.UserDefault:getInstance():getBoolForKey("KW_DATA_NEED_FORCE_UPDATE"..key) then

			ResChecker._scene:hotUpdateFaile("å è½½æ¸¸æå¤±è´¥ï¼è¯·æ£æ¥ç½ç»åéå¯æ¸¸æ", true, key)

		else

			ResChecker._scene:showProgress(100)

			ResChecker._loader.load()

			ResChecker._scene.isHotUpdate = false

			ResChecker._scene:hotUpdateSuccess() 

			ResChecker._isGameNeedHotUpdate()

		end

	end

end



-- ç­æ´è¿åº¦éç¥å½æ°

-- @param stage     å½åè¿è¡çæ¯åªä¸æ­¥

-- @param progress  å½åçè¿åº¦

function hotfixListener:onProgress(stage, progress)

    -- è¿åº¦æ¡æ¾ç¤ºçæ¯ä¸è½½è¿åº¦

    if stage == un.const.HotFixStage.DOWNLOAD then

        -- è¿éå¯ä»¥æ´æ°è¿åº¦æ¡

		ResChecker._scene:showProgress(progress * 100)

    end

end



-- å¯å¨ç­æ´å½æ°

-- @param isFirst   æ¯å¦æ¯æ¸çèµæºåç¬¬ä¸æ¬¡ç­æ´

function ResChecker._startHotFix(isFirst)

    -- isFirst é»è®¤å¼ä¸º false

    isFirst = isFirst or false

	ResChecker._gamesHotUpdata = require("app.hotupdate.games.GameHotUpdateData")	

	--ååå¹¶ä»¥åéé»ç­æ´ä¸æ¥çæä»¶

	un.hotfix.deferMerge.start("Lobby")

	--un.hotfix.deferMerge.start("GameCommon")

	for key, _ in pairs(ResChecker._gamesHotUpdata.HotUpdateList) do

		un.hotfix.deferMerge.start(key)

	end



    -- ç­æ´ä¿¡æ¯ï¼å¯ä»¥æ¾å¨è¿éï¼ä¹å¯ä»¥åèç­æ´ä¸æ ·æ¾å¨ä¸ä¸ªåç¬çæä»¶éé¢

    local hotfixData = {

        HotUpdateList = ResChecker._lobbyHotUpdata.HotUpdateList,

    }



    -- HotFixManager æ¯ç­æ´å¯¹å¤æä¾çæ¥å£ï¼ "HotUpdate" è¡¨ç¤ºmanifestçè·¯å¾

    -- å°è¿ä¸ªå¼æ¼å¨ project.manifest åé¢ï¼å¦ HotUpdate/Lobby/project.manifest

    local manager = un.hotfix.HotFixManager.new(hotfixListener, "GameHotUpdate3", isFirst, true, 0)

    hotfixListener._manager = manager

    -- è°ç¨ start å½æ°å¯å¨ç­æ´

    manager:start(hotfixData)

end



-- å¤§åç­æ´å®æï¼æ£æµå­æ¸¸ææ¯å¦éè¦ç­æ´å½æ°

-- @param isFirst   æ¯å¦æ¯æ¸çèµæºåç¬¬ä¸æ¬¡ç­æ´

function ResChecker._isGameNeedHotUpdate(isFirst)

	-- isFirst é»è®¤å¼ä¸º false

    isFirst = isFirst or false

	ResChecker._gamesHotUpdata = require("app.hotupdate.games.GameHotUpdateData")	

    -- ç­æ´ä¿¡æ¯ï¼å¯ä»¥æ¾å¨è¿é

	local hotfixData = {

        HotUpdateList = ResChecker._gamesHotUpdata.HotUpdateList,

    }

	-- ææ¶å¿½ç¥GameCommon

	-- hotfixData.HotUpdateList["GameCommon"] = ResChecker._gamesHotUpdata.HotUpdateCommon["GameCommon"]

	-- æåä¸ä¸ªåæ°ä¸ºç­æ´æ°ä¼åçº§

    local managerGame = un.hotfix.HotFixManager.new(hotfixListener, "GameHotUpdate3", isFirst, true, 1)

    hotfixListener._manager = managerGame

    -- è°ç¨ start å½æ°å¯å¨ç­æ´

	managerGame:start(hotfixData)

end



return ResChecker