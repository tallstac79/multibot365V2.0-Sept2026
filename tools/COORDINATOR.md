# Coordinator connection

The app listens on port 8767 on a private IPv4 Wi-Fi/Ethernet address, or on the Tailscale tun address (100.64.0.0/10) when Wi-Fi is off. There is no ADB forwarding or host process in the action path. Enable the accessibility service, keep the phone awake/unlocked, and open **Coordinator connection** in the app to read its address and pairing token. Put those values in an untracked `.local/coordinator.json`:

```json
{"url":"http://PHONE_PRIVATE_IP:8767","token":"COPY_THE_PHONE_GENERATED_TOKEN"}
```

Use a trusted private LAN: HTTP bearer authentication does not encrypt traffic. The listener refuses wildcard/public/carrier-mobile binding and non-private peers; Tailscale CGNAT peers and tun bind are allowed. Rotate the token in the app settings when needed. Tokens are generated per installation and never committed. An optional start-page URL is configured on the phone; blank selects its built-in neutral page. The instruction cannot change that URL.

```powershell
python tools/coordinator_client.py health
python tools/coordinator_client.py send instruction.json
python tools/coordinator_client.py result unique-id
```

`instruction.json`:
```json
{"instruction_id":"unique-id","action":"OPEN_AND_TYPE","target_text":"Search","input_text":"Fulham","timeout_ms":15000}
```

Exactly these five fields are required. IDs use 1–64 ASCII letters/digits/underscores/hyphens; target is one alphanumeric word of 1–40 characters; input is 1–128 UTF-16 units; timeout is an integer 100–60000 ms. Current visual acceptance covers visible outlined text fields and English OCR. The action opens Chrome at the configured URL, visually finds the target, focuses via dispatchGesture, commits text once, and verifies exact editor readback plus screenshot OCR. It does not use node trees.

All API requests require `Authorization: Bearer TOKEN`. POST requires `Content-Type: application/json`. API browser Origin headers are rejected. Only the static neutral fixture is public on the private listener.

- `GET /health` or `/state`: heartbeat, state, current instruction, last result, app version, endpoint, PID.
- `POST /instructions`: HTTP 202 durable receipt acknowledgement before execution; poll returned `result_url`.
- `GET /instructions/ID`: 202 while pending; 200 with terminal result.
- `GET /instructions/ID/evidence`: detailed text evidence/timings.
- `GET /instructions/ID/artifacts/before.png` (also focused.png, after.png, field_after.png and OCR .txt files): actual phone artifacts.

Results have `instruction_id`, `status` (PASS or FAIL), `stage`, `detail`, `duration_ms`, plus `execution_count` and internal run ID. Stage is PASS, INVALID_INSTRUCTION, DUPLICATE, TARGET_NOT_FOUND, FOCUS_FAILED, INPUT_FAILED, TEXT_NOT_VERIFIED, TIMEOUT, or INTERNAL_ERROR. Busy admission is HTTP 409 / INTERNAL_ERROR with BUSY detail and does not consume the new ID. Duplicate admission is HTTP 409 / DUPLICATE; its `result_url` still resolves to the original result. A duplicate payload cannot change the accepted work.

SQLite commits IDs before acknowledgement and before action effects. IDs are never evicted. Process/service restarts reconcile already-persisted terminal text evidence; uncertain pending work becomes INTERNAL_ERROR and is never replayed. This provides at-most-once attempts, not guaranteed completion after interruption. Do not clear app data or uninstall if you need the existing deduplication ledger.

The client retries uncertain communications using the same ID and polls the original result. It never creates a new ID to recover a lost response. Requests have bounded framing/body sizes, a bounded worker pool, idle socket timeouts and an absolute five-second socket deadline. Instruction deadlines cover receipt through completion; late runner callbacks cannot act.

## Physical acceptance

Deploy the APK once, remove ADB forwards/reverses and stop the ADB server. Then:

```powershell
python tools/test_coordinator.py --output evidence/coordinator
```

The suite uses HTTP only and asserts localhost port 5037 is closed before and after. It saves instructions, acknowledgements, terminal results, actual PNGs/OCR, duplicate results, malformed requests, health and restart evidence. Its authenticated `/test/restart` endpoint exists only in debuggable builds and kills the process after acknowledging; Android then rebinds the enabled accessibility service. Release builds return 404 for that endpoint.
