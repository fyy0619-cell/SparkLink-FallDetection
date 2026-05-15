function
    -- V100C / Air780EHV minimal SMS capability test.
    -- Purpose: before using the real UART task, verify this firmware
    -- exposes sms.send and the SIM can actually send an SMS.
    -- Usage: change the placeholder number to a test phone, paste the
    -- whole script into Yinerda backend task 1, start it, watch the phone.
    local tname = "min_sms_test"
    local phone = "123xxxx4567"
    local text  = "WS63 fall alert SMS test"

    log.info(tname, "min sms test start")
    -- wait for the module to register on the network
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
