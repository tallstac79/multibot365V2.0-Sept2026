package com.bet365agent;
import org.junit.Test;
import static org.junit.Assert.assertEquals;

public class PowerTrendTest {
    @Test public void pluggedDoesNotMeanAdequatePower() {
        PowerTrend p = new PowerTrend();
        assertEquals("OK", p.observe(0,95,2));
        assertEquals("OK", p.observe(60_000,93,2));
        assertEquals("DRAINING_WHILE_PLUGGED", p.observe(180_000,93,2));
    }
    @Test public void onePercentIsNotEnoughEvidence() {
        PowerTrend p = new PowerTrend();p.observe(0,80,2);
        assertEquals("OK",p.observe(600_000,79,2));
    }
    @Test public void criticallyLowWinsEvenWhileCharging() {
        assertEquals("BATTERY_CRITICAL",new PowerTrend().observe(0,5,2));
        assertEquals("BATTERY_LOW",new PowerTrend().observe(0,15,2));
    }
    @Test public void invalidLevelIsUnknown() {
        assertEquals("UNKNOWN",new PowerTrend().observe(0,-1,0));
        assertEquals("UNKNOWN",new PowerTrend().observe(0,101,2));
    }
    @Test public void actualRechargeClearsDrainWarning() {
        PowerTrend p = new PowerTrend();p.observe(0,80,2);p.observe(600_000,78,2);
        assertEquals("DRAINING_WHILE_PLUGGED",p.observe(610_000,79,2));
        assertEquals("OK",p.observe(620_000,81,2));
    }
    @Test public void powerSourceChangeResetsTrend() {
        PowerTrend p = new PowerTrend();p.observe(0,80,2);
        assertEquals("UNPLUGGED",p.observe(600_000,78,0));
        assertEquals("OK",p.observe(700_000,77,1));
    }
    @Test public void elapsedClockResetDoesNotCarryOldTrend() {
        PowerTrend p = new PowerTrend();p.observe(800_000,80,2);
        assertEquals("OK",p.observe(0,70,2));
    }
}
