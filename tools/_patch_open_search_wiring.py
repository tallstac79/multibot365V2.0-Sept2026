from pathlib import Path

# --- CoordinatorInstruction ---
inst = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/CoordinatorInstruction.java")
t = inst.read_text(encoding="utf-8")
t2 = t.replace(
    'Set<String> allowed = Set.of("instruction_id","action","target_text","input_text","adapter","scenario","query","market","side","sport","line","minimum_price","stake","timeout_ms","place_bet","execution_mode","confirmation_status");',
    'Set<String> allowed = Set.of("instruction_id","action","target_text","input_text","adapter","scenario","query","market","side","sport","line","minimum_price","stake","timeout_ms","place_bet","execution_mode","confirmation_status");'
)
# add OPEN_SEARCH branch before SESSION_CHECK
needle = '} else if(action.equals("SESSION_CHECK")) {'
insert = '''} else if(action.equals("OPEN_SEARCH")) {
            // query optional: omit for open-only; include for Search→type→results harness
            java.util.HashSet<String> openSearchBase = new java.util.HashSet<>(java.util.Arrays.asList(
                "instruction_id","action","adapter","scenario","sport","timeout_ms"));
            java.util.HashSet<String> keys = new java.util.HashSet<>(fields.keySet());
            if(!keys.containsAll(openSearchBase)) throw new IllegalArgumentException("Invalid OPEN_SEARCH schema");
            keys.removeAll(openSearchBase);
            if(!keys.isEmpty() && !(keys.size()==1 && keys.contains("query")))
                throw new IllegalArgumentException("Invalid OPEN_SEARCH extras");
        } else if(action.equals("SESSION_CHECK")) {'''
if needle not in t2:
    raise SystemExit("SESSION_CHECK needle missing")
if "OPEN_SEARCH" not in t2:
    t2 = t2.replace(needle, insert, 1)

t2 = t2.replace(
    'if(!Set.of("OPEN_AND_TYPE","ADAPTER_WORKFLOW","SESSION_CHECK","SESSION_PROBE").contains(action)\n            || !id.matches("[A-Za-z0-9_-]{1,64}") || ((action.equals("SESSION_CHECK") || action.equals("SESSION_PROBE")) ? !text.isEmpty() : text.isEmpty())',
    'if(!Set.of("OPEN_AND_TYPE","ADAPTER_WORKFLOW","SESSION_CHECK","SESSION_PROBE","OPEN_SEARCH").contains(action)\n            || !id.matches("[A-Za-z0-9_-]{1,64}") || ((action.equals("SESSION_CHECK") || action.equals("SESSION_PROBE") || action.equals("OPEN_SEARCH")) ? (action.equals("OPEN_SEARCH") ? false : !text.isEmpty()) : text.isEmpty())'
)
# For OPEN_SEARCH, text may be empty; the ternary above: for OPEN_SEARCH the middle branch is taken with `false` meaning "do not fail on empty". 
# Wait: condition is `? !text.isEmpty() : text.isEmpty()` — if true branch returns !text.isEmpty(), failing when text IS empty for SESSION_*.
# For OPEN_SEARCH I want never fail on empty/non-empty from this check. So false = don't trigger IllegalArgumentException from this clause.
# Good.

t2 = t2.replace(
    'if(action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK")) {\n            SiteAdapters.validate(adapter,scenario);\n            if(!Set.of("football","basketball").contains(sport)) throw new IllegalArgumentException("Invalid sport");\n        }',
    'if(action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK") || action.equals("OPEN_SEARCH")) {\n            SiteAdapters.validate(adapter,scenario);\n            if(!Set.of("football","basketball").contains(sport)) throw new IllegalArgumentException("Invalid sport");\n        }'
)
inst.write_text(t2, encoding="utf-8")
print("CoordinatorInstruction updated", "OPEN_SEARCH" in t2)

# --- CoordinatorAgent execute + wake ---
agent = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/CoordinatorAgent.java")
a = agent.read_text(encoding="utf-8")
# wake before interactive check
old_exec = '''            PowerManager power = (PowerManager) service.getSystemService(android.content.Context.POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager) service.getSystemService(android.content.Context.KEYGUARD_SERVICE);
            if (!power.isInteractive()) { complete(row, "FOCUS_FAILED", "Phone must be awake and unlocked"); return; }'''
new_exec = '''            PowerManager power = (PowerManager) service.getSystemService(android.content.Context.POWER_SERVICE);
            KeyguardManager keyguard = (KeyguardManager) service.getSystemService(android.content.Context.KEYGUARD_SERVICE);
            // Best-effort screen wake (no ADB): ACQUIRE_CAUSES_WAKEUP. Unlock still required if keyguard is secure.
            try {
                if (power != null && !power.isInteractive()) {
                    @SuppressWarnings("deprecation")
                    PowerManager.WakeLock wake = power.newWakeLock(
                        PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP | PowerManager.ON_AFTER_RELEASE,
                        "bet365agent:instruction");
                    wake.acquire(4000L);
                    try { Thread.sleep(250); } catch (InterruptedException ignored) {}
                    if (wake.isHeld()) wake.release();
                }
            } catch (Exception ignored) {}
            if (power == null || !power.isInteractive()) { complete(row, "FOCUS_FAILED", "Phone must be awake and unlocked"); return; }'''
if old_exec not in a:
    raise SystemExit("execute wake needle missing")
a = a.replace(old_exec, new_exec, 1)

old_wf = '''            if(instruction.action.equals("ADAPTER_WORKFLOW") || instruction.action.equals("SESSION_CHECK") || instruction.action.equals("SESSION_PROBE")) {
                if(!runner.startExternal(instruction.runId,remaining(row,instruction.timeout))) {complete(row,"INTERNAL_ERROR","Runner rejected workflow");return;}
                VisualSession session=new VisualSession(service,runner,instruction.runId,instruction.adapter);
                if(instruction.action.equals("SESSION_PROBE")) { new SessionProbeWorkflow(session).start(); return; }
                SiteAdapter adapter=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                if(instruction.action.equals("SESSION_CHECK")) new SessionCheckWorkflow(session,adapter).start();
                else new AdapterWorkflow(session,adapter).start(instruction.text,instruction.market,instruction.side,instruction.line,instruction.minimumPrice,instruction.stake,instruction.executionMode,instruction.confirmationStatus);
                return;
            }'''
new_wf = '''            if(instruction.action.equals("ADAPTER_WORKFLOW") || instruction.action.equals("SESSION_CHECK") || instruction.action.equals("SESSION_PROBE") || instruction.action.equals("OPEN_SEARCH")) {
                if(!runner.startExternal(instruction.runId,remaining(row,instruction.timeout))) {complete(row,"INTERNAL_ERROR","Runner rejected workflow");return;}
                VisualSession session=new VisualSession(service,runner,instruction.runId,instruction.adapter);
                if(instruction.action.equals("SESSION_PROBE")) { new SessionProbeWorkflow(session).start(); return; }
                SiteAdapter adapter=SiteAdapters.create(instruction.adapter,session,endpoint(),instruction.scenario,instruction.id,instruction.sport,instruction.stake);
                if(instruction.action.equals("SESSION_CHECK")) new SessionCheckWorkflow(session,adapter).start();
                else if(instruction.action.equals("OPEN_SEARCH")) new SearchOpenWorkflow(session,adapter,instruction.text).start();
                else new AdapterWorkflow(session,adapter).start(instruction.text,instruction.market,instruction.side,instruction.line,instruction.minimumPrice,instruction.stake,instruction.executionMode,instruction.confirmationStatus);
                return;
            }'''
if old_wf not in a:
    raise SystemExit("workflow branch needle missing")
a = a.replace(old_wf, new_wf, 1)

a = a.replace(
    'boolean workflow=action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK") || action.equals("SESSION_PROBE");',
    'boolean workflow=action.equals("ADAPTER_WORKFLOW") || action.equals("SESSION_CHECK") || action.equals("SESSION_PROBE") || action.equals("OPEN_SEARCH");'
)
a = a.replace(
    'if(proof!=null && (completedAction.equals("ADAPTER_WORKFLOW") || completedAction.equals("SESSION_CHECK") || completedAction.equals("SESSION_PROBE"))) {',
    'if(proof!=null && (completedAction.equals("ADAPTER_WORKFLOW") || completedAction.equals("SESSION_CHECK") || completedAction.equals("SESSION_PROBE") || completedAction.equals("OPEN_SEARCH"))) {'
)
agent.write_text(a, encoding="utf-8")
print("CoordinatorAgent updated")

# manifest WAKE_LOCK
man = Path("android/Bet365Agent/app/src/main/AndroidManifest.xml")
m = man.read_text(encoding="utf-8")
if "WAKE_LOCK" not in m:
    m = m.replace(
        '<uses-permission android:name="android.permission.INTERNET" />',
        '<uses-permission android:name="android.permission.INTERNET" />\n    <uses-permission android:name="android.permission.WAKE_LOCK" />'
    )
    man.write_text(m, encoding="utf-8")
    print("manifest WAKE_LOCK added")
else:
    print("manifest already has WAKE_LOCK")

# version bump
gradle = Path("android/Bet365Agent/app/build.gradle.kts")
g = gradle.read_text(encoding="utf-8")
g = g.replace("versionCode = 34", "versionCode = 35").replace('versionName = "0.6.22-login"', 'versionName = "0.6.23-search"')
gradle.write_text(g, encoding="utf-8")
print("version -> 0.6.23-search / 35")
