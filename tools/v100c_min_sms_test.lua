function
    -- V100C / Air780EHV 短信能力最小验证脚本。
    -- 用途：在接正式 UART 任务前，先单独确认该固件支持 sms.send 且 SIM 能发短信。
    -- 用法：把占位号码改成测试手机号，整段粘到银尔达后台任务1，启动后看手机是否收到短信。
    local tname = "min_sms_test"
    local phone = "123xxxx4567"
    local text  = "WS63 fall alert SMS test"

    log.info(tname, "min sms test start")
    -- 等模块注册到网络后再发
    sys.wait(8000)

    if type(sms) ~= "table" or type(sms.send) ~= "function" then
        log.info(tname, "sms lib NOT available in this firmware")
    else
        log.info(tname, "sms send", phone)
        local ok = sms.send(phone, text)
        log.info(tname, "sms send result", ok)
    end

    while true do
        sys.wait(1000)
    end
end
