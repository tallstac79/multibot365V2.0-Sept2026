package com.bet365agent;

/** Diagnostic only. Never participates in admission, session recovery or workflow decisions. */
final class PowerTrend {
    private int baseline = -1;
    private long baselineAt;
    private int previousPlug = -1;
    private boolean draining;

    synchronized String observe(long elapsedMs, int level, int plugged) {
        if (level < 0 || level > 100) return "UNKNOWN";
        if (baseline < 0 || elapsedMs < baselineAt || plugged != previousPlug || level > baseline) {
            baseline = level; baselineAt = elapsedMs; draining = false;
        }
        previousPlug = plugged;
        // A percentage trend is more useful than a single noisy current measurement or the USB-present flag.
        if (plugged != 0 && elapsedMs - baselineAt >= 180_000L && baseline - level >= 2) draining = true;
        if (level <= 5) return "BATTERY_CRITICAL";
        if (level <= 15) return "BATTERY_LOW";
        if (plugged == 0) return "UNPLUGGED";
        return draining ? "DRAINING_WHILE_PLUGGED" : "OK";
    }
}
