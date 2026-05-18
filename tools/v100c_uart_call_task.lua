function
    -- 银尔达 DTU 任务: 跌倒报警 -> 拨号 + 发短信  (最终可用版)
    -- 数据来源: WS63(板B) 经 UART 发来的整行 JSON, 以 \r\n 结尾
    --   {"cmd":"call","phone":"1xxxxxxxxxx", ...}
    --   {"cmd":"sms" ,"phone":"1xxxxxxxxxx","text":"Fall detected ...", ...}
    -- 前提: 移动/联通普通卡(非电信、非物联网卡); 已开 VoLTE; 固件 >= V1.1.13
    local tname = "fall_alert"
    -- 核心状态变量
    local uid = 2                          --WS63 实测接在 DTU 串口 id=2(uarttest 验证)
    local call_counter = 0
    local caller_number = ""
    local outgoing_number = "123xxxx4567"  --默认拨出号码(实际号码由 WS63 的 JSON 下发)
    local default_sms = "Fall detected, please check on the elder."  --默认短信内容
    local is_connected, is_in_call, is_dialing = false, false, false
    local dial_start_time = 0
    local dial_timer = nil
    local rxbuf = ""                       --串口分包/粘包重组缓存

    -- 重置通话状态
    local function resetCallState()
        is_connected, is_in_call, is_dialing = false, false, false
        call_counter, caller_number, dial_start_time = 0, "", 0
        -- 清理定时器
        if dial_timer then
            sys.timerStop(dial_timer)
            dial_timer = nil
        end
        log.info(tname, "resetCallState", "通话状态已重置")
    end

    -- 拨号超时检测(30秒)
    local function checkDialTimeout()
        dial_start_time = dial_start_time + 1
        log.info(tname, "checkDialTimeout", "拨号超时检查", dial_start_time, "秒")
        if dial_start_time >= 30 and is_dialing then
            log.info(tname, "checkDialTimeout", "拨号超时，自动挂断")
            cc.hangUp()
            resetCallState()
        end
    end

    -- 发起呼叫
    local function makeCall()
        if is_dialing or is_in_call then
            log.info(tname, "makeCall", "通话中，跳过呼叫")
            return false
        end
        is_dialing = true
        dial_start_time = 0
        log.info(tname, "makeCall", "拨打号码", outgoing_number)

        local result = cc.dial(0, outgoing_number)
        log.info(tname, "makeCall", "拨号结果", result)

        if result then
            dial_timer = sys.timerLoopStart(checkDialTimeout, 1000)
        else
            resetCallState()
            log.info(tname, "makeCall", "拨号失败")
            return false
        end
        return true
    end

    -- 通话状态处理
    local function handle_scenario(status)
        -- 通话连接/开始
        if status == "CONNECTED" or status == "SPEECH_START" then
            log.info(tname, "handle_scenario", status == "CONNECTED" and "呼叫已连接" or "通话开始")
            is_connected, is_in_call, is_dialing = true, true, false
            -- 停止拨号超时定时器
            if dial_timer then
                sys.timerStop(dial_timer)
                dial_timer = nil
            end
        -- 来电处理：响铃2声自动接听
        elseif status == "INCOMINGCALL" then
            caller_number = cc.lastNum() or "未知号码"
            call_counter = call_counter + 1
            log.info(tname, "handle_scenario", "收到来电", caller_number, "响铃次数", call_counter)
            if call_counter >= 2 then
                log.info(tname, "handle_scenario", "自动接听")
                cc.accept(0)
                call_counter = 0
            end
        -- 通话结束/失败：统一重置状态
        elseif status == "DISCONNECTED" or status == "MAKE_CALL_FAILED" or status == "HANGUP_CALL_DONE" then
            local msg = {
                DISCONNECTED = "对方挂断，通话结束",
                MAKE_CALL_FAILED = "呼叫失败",
                HANGUP_CALL_DONE = "挂断完成"
            }
            log.info(tname, "handle_scenario", msg[status])
            resetCallState()
        end
    end

    -- 处理一条 call 指令
    local function do_call(phone)
        outgoing_number = phone
        -- 挂断当前通话
        if is_in_call or is_dialing then
            log.info(tname, "正在通话/拨号中，先挂断")
            cc.hangUp()
            sys.wait(2000)
        end
        -- 发起新呼叫
        makeCall()
        log.info(tname, "呼叫已发起，等待连接")
    end

    -- 处理一条 sms 指令
    local function do_sms(phone, text)
        local r = SmsSend(phone, text or default_sms)   --返回 1 成功 / 0 失败
        log.info(tname, "do_sms", "发送短信", phone, "结果", r)
    end

    -- 处理一条 hangup 指令
    local function do_hangup()
        log.info(tname, "收到服务器挂断指令")
        if is_in_call or is_dialing then
            cc.hangUp()
            log.info(tname, "已执行挂断操作")
            sys.wait(1000)
            resetCallState()
        else
            log.info(tname, "当前无通话，无需挂断")
        end
    end

    -- 放最前面: 一上电就停内部处理并开始缓存串口数据, 不受 WS63 发送时机影响
    UartStopProRecCh(1)

    -- 订阅电话状态
    sys.subscribe("CC_IND", function(status)
        log.info(tname, "CC状态", status)
        handle_scenario(status)
        if status == "READY" then
            sys.publish("CC_READY")
        end
    end)

    -- 初始化流程
    log.info(tname, "等待电话系统就绪")
    sys.waitUntil("CC_READY")
    cc.init(0)
    log.info(tname, "电话系统初始化完成")

    -- 音频音量配置
    audio.micVol(0, 70)
    audio.vol(0, 70)

    while true do
        -- 1) 取空串口缓存(可能分包, 循环读到 nil 为止)
        while true do
            local rdata = UartGetRecChAndDel(uid)
            if not rdata then break end
            rxbuf = rxbuf .. rdata
        end

        -- 2) 按 \r\n 拆出本轮所有完整 JSON 指令
        local cmds = {}
        while true do
            local p = string.find(rxbuf, "\n")
            if not p then break end
            local line = string.gsub(string.sub(rxbuf, 1, p), "[\r\n]", "")
            rxbuf = string.sub(rxbuf, p + 1)
            if #line > 0 then
                log.info(tname, "收到服务器数据", line)
                local ok, j = pcall(json.decode, line)
                if ok and type(j) == "table" and j.cmd then
                    cmds[#cmds + 1] = j
                else
                    log.info(tname, "丢弃非法数据", line)
                end
            end
        end
        if #rxbuf > 1024 then rxbuf = "" end    --异常长数据保护

        -- 3) 电话优先: 同一批先全部处理 call, 再处理 sms / hangup
        for i = 1, #cmds do
            if cmds[i].cmd == "call" and cmds[i].phone then
                do_call(cmds[i].phone)
            end
        end
        for i = 1, #cmds do
            local j = cmds[i]
            if j.cmd == "sms" and j.phone then
                do_sms(j.phone, j.text)
            elseif j.cmd == "hangup" then
                do_hangup()
            end
        end

        sys.wait(1000)
    end
end
