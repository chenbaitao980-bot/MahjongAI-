local NetEngine = class("NetEngine")

NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED = "EVENT_NET_ENGINE_LINKSTATUS_CHANGED"
NetEngine.EVENT_RELINK_SRS = "EVENT_RELINK_SRS"

local TCP_CONNECT_TIMEOUT = 10000

function NetEngine:ctor()
    cc(self):addComponent("components.behavior.EventProtocol"):exportMethods()

    self._tcpList = {}
    self._protocolCallBackByObj = {}
end

function NetEngine:getInstance()
    if NetEngine._netEngine == nil then
        NetEngine._netEngine = NetEngine.new()
    end
    return NetEngine._netEngine
end

function NetEngine:addSRS(groupId, tcp)
    if not groupId or not tcp then
        return
    end

    if self._tcpList[groupId] then
        return
    end

    self._tcpList[groupId] = tcp
end

function NetEngine:removeSRS(groupId)
    if not groupId then
        return
    end

    if not self._tcpList[groupId] then
        return
    end

    self._tcpList[groupId]:removeAllLinkStateScriptFunc()
    -- c++ 方法调用remove就会崩溃，lua层释放对象暂不处理
    if cc.Application:getInstance():getTargetPlatform() == cc.PLATFORM_OS_ANDROID then
        self._tcpList[groupId]:close()
    else
        self._tcpList[groupId]:destroy()
    end
    self._tcpList[groupId] = nil
end

function NetEngine:removeAllSRS()
    for k, _ in pairs(self._tcpList) do
        self:removeSRS(k)
    end
end

function NetEngine:getAllSRS()
    return self._tcpList
end

function NetEngine:getSRSBySRSGroupID(groupId)
    return self._tcpList[groupId]
end

function NetEngine:reLinkSRS(groupId)
    local SRS = self:getSRSBySRSGroupID(groupId)
    if SRS then
        local linkstate = SRS:getLinkState()
        if linkstate == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
            return
        end
    end

    self:dispatchEvent({name = NetEngine.EVENT_RELINK_SRS})
end

function NetEngine:onMsgCallBack(groupID, msgid, buff, len, processid)
    if groupID then
        local callBackList = self._protocolCallBackByObj[groupID] or {}
        for _, callBack in pairs(callBackList) do
            if callBack.func and callBack.pid == processid then
                callBack.func(callBack.obj, msgid, buff, len, processid)
            end
        end
    end
    self:onMessage(msgid, buff, len, processid, groupID)
end

-- 网络协议事件分发
function NetEngine:onMessage(msgid, buff, len, processid, groupID)
    self:dispatchEvent({name = processid .. "_" .. msgid, msg = {msgid = msgid, buff = buff, len = len, processid = processid,srsGroupID = groupID}})
    -- if msgid == 11200 then
    --     local sToClientData = CF.GameMProtocol.ServerToClientMessage:new()
    --     sToClientData:bistream(buff, len)
    --     local subXYID = sToClientData.cmdid
    --     print("NetEngine onMessage subXYID = " .. subXYID)
    --     return 
    -- end
    if groupID then
        print("【"..groupID.."】1111111111 NetEngine onMessage msgid = " .. msgid)
    else
        print("【0】1111111111 NetEngine onMessage msgid = " .. msgid)
    end
    
end

function NetEngine:sendProtocol(protocol, processID, appID, groupId)
    if groupId == 0 then
        groupId = XH.areaData:getSrsGroupID()
    end
    groupId = groupId or XH.areaData:getSrsGroupID()

    if groupId == 0 then
        return
    end

    local tcp = self:getSRSBySRSGroupID(groupId)
    if tcp == nil or tcp:getLinkState() ~= XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
        local protocolData = {protocol = protocol, processID = processID, appID = appID, groupId = groupId}
        self:startTcp(groupId, protocolData)
        return
    end

    tcp:sendMessageStream(processID, appID, protocol.XY_ID, protocol:bostream())
end

function NetEngine:sendProtoBuf(reqData, processID, appID, groupId)
    local tcp = self:getSRSBySRSGroupID(groupId)
    if tcp == nil or tcp:getLinkState() ~= XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
        local protocolData = {reqData = reqData, processID = processID, appID = appID, groupId = groupId}
        self:startTcpPB(groupId, protocolData)
        return
    end
    tcp:sendMessagePB(processID, appID, reqData.XY_ID, reqData.data)
end

function NetEngine:startTcpPB(groupId, protocolData)
    local newTcp = self:getSRSBySRSGroupID(groupId)
    if not newTcp then
        newTcp = require("app.Net.TcpConnection").new(groupId)
        newTcp:setOnMessageEventCallback(handler(self, self.onMsgCallBack))
        self:addSRS(groupId, newTcp)
    end

    local connectInfo = self:getTcpConnectInfoByGroupId(groupId)
    if not connectInfo then
        return
    end

    newTcp:addLinkStateScriptFunc(function(linkState)
        if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
            self:sendProtoBuf(protocolData.reqData, protocolData.processID, protocolData.appID, protocolData.groupId)
        end
        self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
    end)
    newTcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), TCP_CONNECT_TIMEOUT)
end

function NetEngine:sendRawData(XY_ID, protocol, processID, appID, groupId)
    if groupId == 0 then
        groupId = XH.areaData:getSrsGroupID()
    end
    groupId = groupId or XH.areaData:getSrsGroupID()

    if groupId == 0 then
        return
    end

    local tcp = self:getSRSBySRSGroupID(groupId)
    if not tcp or tcp:getLinkState() ~= XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
        if not tcp then
            tcp = require("app.Net.TcpConnection").new(groupId)
            tcp:setOnMessageEventCallback(handler(self, self.onMsgCallBack))
            self:addSRS(groupId, tcp)
        end
        local connectInfo = self:getTcpConnectInfoByGroupId(groupId)
        if not connectInfo then
            return
        end
        tcp:addLinkStateScriptFunc(function(linkState)
            if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
                NetEngine.sendRawData(self, XY_ID, protocol, processID, appID, groupId)
            end
            self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
        end)
        tcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), TCP_CONNECT_TIMEOUT)
        return
    end

    tcp:sendMessageData(processID, appID, XY_ID, protocol)
end

function NetEngine:startTcp(groupId, protocolData)
    local newTcp = self:getSRSBySRSGroupID(groupId)
    if not newTcp then
        newTcp = require("app.Net.TcpConnection").new(groupId)
        newTcp:setOnMessageEventCallback(handler(self, self.onMsgCallBack))
        self:addSRS(groupId, newTcp)
    end

    local connectInfo = self:getTcpConnectInfoByGroupId(groupId)
    if not connectInfo then
        return
    end

    newTcp:addLinkStateScriptFunc(function(linkState)
        if linkState == XH.SRS_LINK_STATE.LINK_STATE_SUCCESS then
            self:sendProtocol(protocolData.protocol, protocolData.processID, protocolData.appID, protocolData.groupId)
        end
        self:dispatchEvent({name = NetEngine.EVENT_NET_ENGINE_LINKSTATUS_CHANGED})
    end)
    newTcp:connect(connectInfo.id, connectInfo.ip, tostring(connectInfo.port), TCP_CONNECT_TIMEOUT)
end

function NetEngine:addProtocolScriptFuncByObj(object, callBackFunc, processID, groupId)
    if not groupId then
        return
    end
    processID = processID or 0

    self._protocolCallBackByObj[groupId] = self._protocolCallBackByObj[groupId] or {}
    for _, second in pairs(self._protocolCallBackByObj[groupId]) do
        if second.obj == object and second.func == callBackFunc then
            return false
        end
    end
    table.insert(self._protocolCallBackByObj[groupId], {obj = object, func = callBackFunc, pid = processID})
end

function NetEngine:removeProtocolScriptFuncByObj(object, callBackFunc, groupId)
    if not groupId then
        return
    end

    self._protocolCallBackByObj[groupId] = self._protocolCallBackByObj[groupId] or {}
    if callBackFunc then
        for first, second in pairs(self._protocolCallBackByObj[groupId]) do
            if second.obj == object and second.func == callBackFunc then
                self._protocolCallBackByObj[groupId][first] = nil
                break
            end
        end
    else
        for first, second in pairs(self._protocolCallBackByObj[groupId]) do
            if second.obj == object then
                self._protocolCallBackByObj[groupId][first] = nil
            end
        end
    end
end

function NetEngine:getTcpConnectInfoByGroupId(groupId)
    local list = XH.LOCAL_TCP_LIST[groupId] or {} -- 本地srs
    if XH.areaData:isSupportSRS50() then
        for k,v in pairs(XH.LOCAL_TCP_LIST_50) do
            if k == groupId then
                list = XH.LOCAL_TCP_LIST_50[groupId]
                if list and #list > 0 then
                    return list[1]
                end
            end
        end
    end
    -- 策略srs 
    self:getSRSConfigListFromFile(groupId, list)

    local isAbroadSrs = XH.userDefault:getValue(XH.userDefault.KEY_ID.KW_DATA_IS_ABROAD_SRS, false)
    if isAbroadSrs then
        local abroadSrsList = XH.ABROAD_TCP_LIST[groupId] or {}
        local len = #abroadSrsList
        if len > 0 then
            local randomNum = math.random(1, len)
            return abroadSrsList[randomNum]
        end
    end

    if list then
        local len = #list
        if len > 1 then
            local randomNum = math.random(1, len)
            return list[randomNum]
        else
            return list[1]
        end
    else
        return nil
    end
end

function NetEngine:getSRSConfigListFromFile(groupId, srsConfigList)
    local txtFile = io.open(string.format("%s%s%d.json", cc.FileUtils:getInstance():getWritablePath(), "srslist", groupId), "rb")
    if not txtFile then
        return
    end
    local srsText = txtFile:read("*a")
    if string.len(srsText) > 0 then
        local srsList = json.decode(srsText)
        if srsList and #srsList > 0 then
            for i = 1, #srsList do
                local tempSRSItem = {}
                tempSRSItem.id = srsList[i].nAppID
                tempSRSItem.ip = srsList[i].szIP
                tempSRSItem.port = srsList[i].sPort
                if tempSRSItem.ip ~= "" and tempSRSItem.port ~= 0 then
                    srsConfigList[#srsConfigList + 1] = tempSRSItem
                end
            end
        end
    end
    txtFile:close()
end

return NetEngine
