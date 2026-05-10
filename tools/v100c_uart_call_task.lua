-- V100C / Air780EHV DTU UART fall alert call task.
-- Purpose:
--   Receive one JSON line from WS63 over UART, then make a phone call.
-- Test line:
--   {"cmd":"call","phone":"13800138000"}\r\n
-- Adjust these values according to the DTU board manual.
local UART_ID = 1
local UART_BAUD = 115200
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

    -- Prevent an invalid stream from consuming RAM forever.
    if #rxbuf > 512 then
        log.warn(tname, "rxbuf overflow, clear")
        rxbuf = ""
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

    -- Some DTU demos disable protocol receive channel before custom handling.
    -- Keep this line only if the seller confirms it is needed.
    -- PronetStopProRecCh(1)

    uart.setup(UART_ID, UART_BAUD, 8, 1, uart.NONE)
    uart.on(UART_ID, "receive", function(id, len)
        local data = uart.read(id, len)
        feedUartData(data)
    end)

    log.info(tname, "uart ready", UART_ID, UART_BAUD)

    while true do
        sys.wait(1000)
    end
end)
