function
    local tname = "min_call_test"
    local phone = "123xxxx4567"

    sys.subscribe("CC_IND", function(status)
        log.info(tname, "CC_IND", status)
        if status == "READY" then
            sys.publish("CC_READY")
        end
    end)

    log.info(tname, "wait CC_READY")
    sys.waitUntil("CC_READY")
    cc.init(0)
    log.info(tname, "cc init done")

    if audio then
        audio.micVol(0, 70)
        audio.vol(0, 70)
    end

    sys.wait(3000)
    log.info(tname, "dial", phone)
    local ok = cc.dial(0, phone)
    log.info(tname, "dial result", ok)

    while true do
        sys.wait(1000)
    end
end
