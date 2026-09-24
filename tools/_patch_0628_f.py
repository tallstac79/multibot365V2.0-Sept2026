from pathlib import Path
p = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/CoordinatorAgent.java')
t = p.read_text(encoding='utf-8')
old = '''    private void onWorkflowProgress(String stage, long elapsedMs, JSONObject timing) {
        noteProgress(progressInstructionId, stage, elapsedMs, timing);
        // When ENSURE_SESSION / SESSION_CHECK reports AUTHENTICATED via record, noteSession is called from complete path;
        // also treat workflow progress as keepalive for an already AUTHENTICATED session.
        synchronized (sessionLock) {
            if ("AUTHENTICATED".equals(sessionState)) {
                sessionObservedAtMs = System.currentTimeMillis();
                sessionDetail = "job-active progress keepalive @" + stage;
            }
        }
    }

    private synchronized void noteProgress(String instructionId, String stage, long elapsedMs, JSONObject timing) {
        if (instructionId == null) return;
        progressInstructionId = instructionId;
        if (stage != null && !stage.isEmpty()) progressStage = stage;
        progressElapsedMs = elapsedMs;
        lastProgressAtElapsed = SystemClock.elapsedRealtime();
        lastProgressWallMs = System.currentTimeMillis();'''

new = '''    private static boolean advancesWatchdog(String stage) {
        if (stage == null) return false;
        // Capture/noise phases must NOT reset inactivity; only verified ladder stage advances do.
        return java.util.Set.of(
            "STARTED","SESSION_CHECK","SPORTS_HOME","SPORTS_CONTEXT","OPEN_SEARCH","FOCUS",
            "ENTER_QUERY","QUERY_VERIFY","RESULTS_WAIT","FIXTURE_VERIFY","MARKET_NAV",
            "OPEN_HOME","ENSURE_SESSION","DISCOVER_FIXTURE","SELECT_FIXTURE","VERIFY_EVENT",
            "DISCOVER_MARKETS","READ_SELECTION","READ_LINE","READ_PRICE","OPEN_SELECTION",
            "ENTER_STAKE","VERIFY_FINAL_STATE","PREPARE_COMPLETE_EXECUTION","PLACE_BET"
        ).contains(stage);
    }

    private void onWorkflowProgress(String stage, long elapsedMs, JSONObject timing) {
        noteProgress(progressInstructionId, stage, elapsedMs, timing);
        if (!advancesWatchdog(stage)) return;
        // Keep AUTHENTICATED fresh while verified stage progress continues (no UNKNOWN race).
        synchronized (sessionLock) {
            if ("AUTHENTICATED".equals(sessionState)) {
                sessionObservedAtMs = System.currentTimeMillis();
                sessionDetail = "job-active progress keepalive @" + stage;
            }
        }
    }

    private synchronized void noteProgress(String instructionId, String stage, long elapsedMs, JSONObject timing) {
        if (instructionId == null) return;
        progressInstructionId = instructionId;
        boolean advance = advancesWatchdog(stage);
        if (advance && stage != null && !stage.isEmpty()) progressStage = stage;
        progressElapsedMs = elapsedMs;
        if (advance) {
            lastProgressAtElapsed = SystemClock.elapsedRealtime();
            lastProgressWallMs = System.currentTimeMillis();
        }'''

if old not in t:
    raise SystemExit('onWorkflowProgress block missing')
p.write_text(t.replace(old, new, 1), encoding='utf-8')
print('OK watchdog advance filter')
