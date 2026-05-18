function
    -- 银尔达 DTU 串口链路诊断: 同时监听串口 1/2/3, 任一口收到数据 -> 拨号 + 发短信报告是几号口
    -- 用途: 验证 WS63 -> DTU 串口通路, 并确认 WS63 实际接的是哪个 UART id
    -- 用法: 作为「任务」上传 -> 给 DTU 上电 -> 等满 1 分钟 -> 复位 WS63 发数据
    -- 结论参考: 本项目实测 WS63 接在 DTU 串口 id=2
    local tname = "uarttest"
    local target = "123xxxx4567"          --收到数据后拨打/发短信的测试号码, 改成你自己的

    -- 放最前面: 一上电就停内部处理并开始缓存串口数据, WS63 早发也不会丢
    UartStopProRecCh(1)

    -- 电话系统初始化(注册网络可能要几十秒, 期间串口数据已在缓存)
    sys.subscribe("CC_IND", function(status)
        log.info(tname, "CC状态", status)
        if status == "READY" then
            sys.publish("CC_READY")
        end
    end)
    sys.waitUntil("CC_READY")
    cc.init(0)
    audio.micVol(0, 70)
    audio.vol(0, 70)
    log.info(tname, "就绪, 检查串口 1/2/3 缓存...")

    local fired = false
    while true do
        for id = 1, 3 do
            local data = UartGetRecChAndDel(id)
            if data and #data > 0 and not fired then
                fired = true
                log.info(tname, "串口", id, "收到", #data, "字节 -> 拨号+短信")
                cc.dial(0, target)
                sys.wait(2000)
                SmsSend(target, "DTU uart ok: id=" .. id .. " len=" .. #data)
            end
        end
        sys.wait(300)
    end
end
