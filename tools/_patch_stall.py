from pathlib import Path
p = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/AdapterWorkflow.java')
t = p.read_text(encoding='utf-8')
old = '''    void start(String query,String market,String side,String line,String minimumPrice,String stake,String executionMode,String confirmationStatus) {
        final String mode = executionMode == null || executionMode.isEmpty() ? "ready" : executionMode;
        step("SPORTS_HOME",adapter::open_home)'''
new = '''    void start(String query,String market,String side,String line,String minimumPrice,String stake,String executionMode,String confirmationStatus) {
        final String mode = executionMode == null || executionMode.isEmpty() ? "ready" : executionMode;
        // Debug/harness: intentional stall after first stage advance so inactivity watchdog can be proven.
        // Not used by production OddsNotifier tips.
        if ("__STALL__".equals(query)) {
            session.checkpoint("SPORTS_HOME");
            session.put("stall_harness", true);
            session.delay(600_000L).whenComplete((v, error) -> {
                if (session.live()) session.finish("TIMEOUT", "Stall harness absolute wait ended");
            });
            return;
        }
        step("SPORTS_HOME",adapter::open_home)'''
if old not in t:
    raise SystemExit('start() insert point missing')
p.write_text(t.replace(old, new, 1), encoding='utf-8')
print('OK stall harness')
