-- V100C / Air780EHV DTU task for WS63 fall-alert phone calls.
--
-- This version is written for the Yinerda DTU firmware task API, not for a
-- bare LuatOS uart.on() project.
--
-- Hardware path:
--   WS63 TX  -> V100C RXD
--   WS63 RX  <- V100C TXD
--   WS63 GND -> V100C GND
--
-- Confirmed V100C external RXD/TXD channel:
--   UartGetRecChAndDel(1)
--
-- Test line sent from PC serial assistant or WS63:
--   {"cmd":"fall_alert","phone":"13800138000","device":"ws63-fall-client-001","payload":5}\r\n

local UART_ID = 1
local DEFAULT_PHONE = "" -- Optional fallback phone number.
local DIAL_TIMEOUT_MS = 30000

local tname = "fall_uart_call"
local rxbuf = ""
local outgoing_number = nil
local is_dialing = false
local is_in_call = false
local dial_timer = nil

local function resetCallState()
    is_dialing = false
    is_in_call = false
    outgoing_number = nil
    if dial_timer then
        sys.timerStop(dial_timer)
        dial_timer = nil
    end
end

local function checkDialTimeout()
    if is_dialing and not is_in_call then
        log.info(tname, "dial timeout, hangup")
        cc.hangUp(0)
        resetCallState()
    end
end

local function makeCall(phone)
    if not phone or phone == "" then
        log.warn(tname, "empty phone, ignore")
        return false
    end

    if is_in_call or is_dialing then
        log.info(tname, "busy, hangup previous call first")
        cc.hangUp(0)
        sys.wait(2000)
        resetCallState()
    end

    outgoing_number = phone
    is_dialing = true
    log.info(tname, "dial", outgoing_number)

    local ok = cc.dial(0, outgoing_number)
    log.info(tname, "dial result", ok)
    if ok then
        dial_timer = sys.timerStart(checkDialTimeout, DIAL_TIMEOUT_MS)
        return true
    end

    resetCallState()
    return false
end

local function handleCallStatus(status)
    log.info(tname, "CC_IND", status)

    if status == "READY" then
        sys.publish("CC_READY")
        return
    end

    if status == "CONNECTED" or status == "SPEECH_START" then
        is_dialing = false
        is_in_call = true
        if dial_timer then
            sys.timerStop(dial_timer)
            dial_timer = nil
        end
        return
    end

    if status == "DISCONNECTED" or status == "MAKE_CALL_FAILED" or status == "HANGUP_CALL_DONE" then
        resetCallState()
        return
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

    log.info(tname, "uart json", line)
    local ok, obj = pcall(json.decode, line)
    if not ok or type(obj) ~= "table" then
        log.warn(tname, "bad json")
        return
    end

    local cmd = obj.cmd
    local phone = obj.phone or DEFAULT_PHONE

    if (cmd == "call" or cmd == "fall_alert") and type(phone) == "string" then
        makeCall(phone)
    else
        log.warn(tname, "unsupported cmd or phone", cmd, phone)
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

    -- Prevent a malformed stream from consuming RAM forever.
    if #rxbuf > 512 then
        log.warn(tname, "rxbuf overflow, clear")
        rxbuf = ""
    end
end

local function pollUartChannel()
    while true do
        local data = UartGetRecChAndDel(UART_ID)
        if data then
            feedUartData(data)
        else
            sys.wait(100)
        end
    end
end

sys.taskInit(function()
    sys.subscribe("CC_IND", handleCallStatus)

    log.info(tname, "wait CC_READY")
    sys.waitUntil("CC_READY")
    cc.init(0)
    log.info(tname, "cc init done")

    -- Optional audio settings. Keep or remove according to the seller demo.
    if audio then
        audio.micVol(0, 70)
        audio.vol(0, 70)
    end

    -- Required by the Yinerda DTU firmware when a user task wants to consume
    -- serial data by itself instead of letting the built-in transparent
    -- transmission engine process it.
    UartStopProRecCh(1)

    log.info(tname, "uart task ready", UART_ID)
    pollUartChannel()
end)
