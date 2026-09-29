package com.bet365agent;
import org.junit.Test;
import static org.junit.Assert.*;
public class StartupRecoveryTest {
    @Test public void nonSecureGrantedNewBootIsEligible(){assertTrue(StartupRecovery.eligible(true,false,true,true,false,30000,24,23));}
    @Test public void secureLockIsNeverDismissed(){assertFalse(StartupRecovery.eligible(true,true,true,true,false,30000,24,23));}
    @Test public void disabledLocalGrantIsRespected(){assertFalse(StartupRecovery.eligible(false,false,true,true,false,30000,24,23));}
    @Test public void encryptedStorageMustAlreadyBeUnlocked(){assertFalse(StartupRecovery.eligible(true,false,false,true,false,30000,24,23));}
    @Test public void doesNotLaunchIfAlreadyUnlocked(){assertFalse(StartupRecovery.eligible(true,false,true,false,false,30000,24,23));}
    @Test public void neverTakesScreenDuringActiveWork(){assertFalse(StartupRecovery.eligible(true,false,true,true,true,30000,24,23));}
    @Test public void doesNotFightManualLockAfterBoot(){assertFalse(StartupRecovery.eligible(true,false,true,true,false,120000,24,23));}
    @Test public void oneAttemptPerBoot(){assertFalse(StartupRecovery.eligible(true,false,true,true,false,30000,24,24));}
    @Test public void unknownBootFailsClosed(){assertFalse(StartupRecovery.eligible(true,false,true,true,false,30000,-1,-2));}
}
