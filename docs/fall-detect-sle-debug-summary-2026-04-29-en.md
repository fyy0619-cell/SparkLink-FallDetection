# Fall Detect + SLE Debugging Summary (2026-04-29)

## Goal
- Server detects a fall event and sends alert `0x05` to Client over SLE/SSAP.
- Client receives `0x05`, triggers buzzer alarm, and auto-stops after 10 seconds.

## Issues Encountered
1. `ssapc_register_client failed: 0x80006011` on Client.
2. Fall detection task was started twice, causing duplicated callbacks/state conflicts.
3. Client only received handshake `0x01`, but not alert `0x05`.
4. Server printed `WARNING: FALL DETECTED`, but sometimes did not send alert.

## Root Causes
- SSAP client registration was called before SLE stack became ready.
- Duplicate task entry registration caused repeated initialization.
- `0x01` is handshake, not alarm; buzzer logic is correctly bound to `0x05`.
- Original window-based trigger did not align with AI valid-output timing (`-1` frames).

## Fixes Applied
- Register SSAP client after `enable_sle` success callback.
- Remove duplicate `app_run(Fall_Detect_Entry)` path.
- Match service handle by UUID `0xABCD` on Client side.
- Add 10-second auto-stop buzzer guard logic.
- Temporarily injected test `0x05` after connect to verify end-to-end path, then removed.
- Changed trigger policy to single-hit alert (`status == 1` sends immediately).
- Reduced cooldown from 5s to 2s for higher sensitivity.

## Protocol Notes
- `0x01`: handshake / link activation
- `0x05`: fall alert
- `0x06`: client ACK

## Tech Stack and Principles
- **SLE (NearLink):** advertising, scanning, connection, pairing.
- **SSAP:** service/property-based access model over SLE.
- **Notify + ACK:** low-latency push plus optional business-level confirmation.
- **State machine order:** enable -> register callbacks/client -> connect/pair -> MTU -> discovery -> notify handling.

## Current Status
- Client connects and discovers service reliably.
- Server sends alert on first fall hit.
- Client buzzer alarms and auto-stops after 10 seconds.
- Sensitivity improved (single-hit + 2s cooldown).

## Suggested Next Steps
- Add `0x00` clear command for remote early buzzer stop.
- Add sequence/timestamp to alert payload.
- Log every `sle_send_fall_alert` return code for better field diagnostics.
