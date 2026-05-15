function
    local tname = "fall_uart_call"
    local UART_ID = 1
    local DIAL_TIMEOUT_SEC = 30

    local rxbuf = ""
    local outgoing_number = ""
    local is_dialing = false
    local is_in_call = false
    local dial_seconds = 0
    local dial_timer = nil

    local function resetCallState()
        is_dialing = false
        is_in_call = false
        dial_seconds = 0
        if dial_timer then
            sys.timerStop(dial_timer)
            dial_timer = nil
        end
    end

    local function checkDialTimeout()
        dial_seconds = dial_seconds + 1
        if is_dialing and dial_seconds >= DIAL_TIMEOUT_SEC then
            log.info(tname, "dial timeout, hangup")
            cc.hangUp()
            resetCallState()
        end
    end

    local function makeCall(phone)
        if not phone or phone == "" then
            log.info(tname, "empty phone, ignore")
            return false
        end

        if is_dialing or is_in_call then
            log.info(tname, "busy, hangup first")
            cc.hangUp()
            sys.wait(2000)
            resetCallState()
        end

        outgoing_number = phone
        is_dialing = true
        dial_seconds = 0
        log.info(tname, "dial", outgoing_number)

        local ok = cc.dial(0, outgoing_number)
        log.info(tname, "dial result", ok)
        if ok then
            dial_timer = sys.timerLoopStart(checkDialTimeout, 1000)
            return true
        end

        resetCallState()
        return false
    end

    local function sendSms(phone, text)
        if not phone or phone == "" then
            log.info(tname, "empty phone, ignore sms")
            return false
        end
        if not text or text == "" then
            text = "Fall detected. Please check now."
        end
        -- sms 库由固件提供；若该固件未带 sms 库则跳过，不影响打电话
        if type(sms) ~= "table" or type(sms.send) ~= "function" then
            log.info(tname, "sms lib not available in this firmware")
            return false
        end
        local ok = sms.send(phone, text)
        log.info(tname, "sms send", phone, ok)
        return ok
    end

    local function handleCallStatus(status)
        log.info(tname, "CC_IND", status)

        if status == "READY" then
            sys.publish("CC_READY")
        elseif status == "CONNECTED" or status == "SPEECH_START" then
            is_dialing = false
            is_in_call = true
            if dial_timer then
                sys.timerStop(dial_timer)
                dial_timer = nil
            end
        elseif status == "DISCONNECTED" or status == "MAKE_CALL_FAILED" or status == "HANGUP_CALL_DONE" then
            resetCallState()
        end
    end

    local function trimLine(line)
        line = line:gsub("^%s+", "")
        line = line:gsub("%s+$", "")
        return line
    end

    local function handleJsonLine(line)
        line = trimLine(line)
        if line == "" then
            return
        end

        log.info(tname, "uart line", line)
        local ok, obj = pcall(json.decode, line)
        if not ok or type(obj) ~= "table" then
            log.info(tname, "bad json")
            return
        end

        if (obj.cmd == "call" or obj.cmd == "fall_alert") and type(obj.phone) == "string" then
            makeCall(obj.phone)
        elseif obj.cmd == "sms" and type(obj.phone) == "string" then
            sendSms(obj.phone, obj.text)
        else
            log.info(tname, "unsupported cmd or phone", obj.cmd, obj.phone)
        end
    end

    local function feedUartData(data)
        if not data or data == "" then
            return
        end

        rxbuf = rxbuf .. data
        while true do
            local pos = rxbuf:find("\n", 1, true)
            if not pos then
                break
            end

            local line = rxbuf:sub(1, pos - 1)
            rxbuf = rxbuf:sub(pos + 1)
            line = line:gsub("\r", "")
            handleJsonLine(line)
        end

        if #rxbuf > 512 then
            log.info(tname, "rxbuf overflow, clear")
            rxbuf = ""
        end
    end

    sys.subscribe("CC_IND", handleCallStatus)

    log.info(tname, "wait CC_READY")
    sys.waitUntil("CC_READY")
    cc.init(0)
    log.info(tname, "cc init done")

    if audio then
        audio.micVol(0, 70)
        audio.vol(0, 70)
    end

    UartStopProRecCh(UART_ID)
    log.info(tname, "uart ready", UART_ID)

    while true do
        local data = UartGetRecChAndDel(UART_ID)
        if data then
            feedUartData(data)
        end
        sys.wait(100)
    end
end
