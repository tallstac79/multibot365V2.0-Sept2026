package com.bet365agent;

import static org.junit.Assert.*;
import java.util.*;
import org.junit.Test;

public class ExecutionHardeningTest {
    @Test public void basketballTotalsAllowOneFullPointStepFromOriginalAlert() {
        for (String market : Arrays.asList("TOTAL", "TOTALS")) {
            assertTrue(ExecutionTolerance.line(market,"OVER","165.5","166.5","1.0"));
            assertFalse(ExecutionTolerance.line(market,"OVER","165.5","167.5","1.0"));
            assertTrue(ExecutionTolerance.line(market,"UNDER","165.5","164.5","1.0"));
            assertFalse(ExecutionTolerance.line(market,"UNDER","165.5","163.5","1.0"));
            assertTrue(ExecutionTolerance.line(market,"OVER","165.5","160.5","1.0"));
            assertTrue(ExecutionTolerance.line(market,"UNDER","165.5","170.5","1.0"));
        }
    }
    @Test public void originalAlertAllowanceHandlesSignsAndDoesNotCompound() {
        for (String side : Arrays.asList("HOME","AWAY")) {
            for (int sign : new int[]{1,-1}) {
                for (String magnitude : Arrays.asList("25.5","15.5","10.5")) {
                    java.math.BigDecimal line = new java.math.BigDecimal(magnitude).multiply(new java.math.BigDecimal(sign));
                    assertTrue(ExecutionTolerance.line("SPREAD",side,line.toPlainString(),line.subtract(java.math.BigDecimal.ONE).toPlainString(),"1"));
                }
            }
            assertFalse(ExecutionTolerance.line("SPREAD",side,"-5.5","-6.5","0.55"));
            assertFalse(ExecutionTolerance.line("SPREAD",side,"1.5","0.5","0.15"));
            assertTrue(ExecutionTolerance.line("SPREAD",side,"-10.5","-11","1"));
            assertFalse(ExecutionTolerance.line("SPREAD",side,"-10.5","-12","1"));
            assertTrue(ExecutionTolerance.line("SPREAD",side,"-5.5","1.5","0.55"));
        }
        assertTrue(ExecutionTolerance.price("1.75","1.75"));
        assertFalse(ExecutionTolerance.price("1.74","1.75"));
        assertTrue(ExecutionTolerance.price("2.50","1.75"));
        assertFalse(ExecutionTolerance.price("NaN","1.75"));
        assertFalse(ExecutionTolerance.price("1.83",""));
    }
    @Test public void freshSlipQuoteUsesOriginalFloorAfterIntermediateRead() {
        HeldSlipQuote first = HeldSlipQuote.read(Arrays.asList(line("Nassjo +13.0 2.10",1180),line("Point Spread",1219)),"Nassjo","SPREAD",1324);
        HeldSlipQuote next = HeldSlipQuote.read(Arrays.asList(line("Nassjo +12.5 2.04",1180),line("Point Spread",1219)),"Nassjo","SPREAD",1324);
        HeldSlipQuote bad = HeldSlipQuote.read(Arrays.asList(line("Nassjo +12.0 1.95",1180),line("Point Spread",1219)),"Nassjo","SPREAD",1324);
        for (HeldSlipQuote q : Arrays.asList(first,next)) {
            assertNotNull(q);assertTrue(ExecutionTolerance.line("SPREAD","AWAY","13.5",q.line,"1"));
            assertTrue(ExecutionTolerance.price(q.price,"2.04"));
        }
        assertNotNull(bad);assertFalse(ExecutionTolerance.line("SPREAD","AWAY","13.5",bad.line,"1"));
        assertFalse(ExecutionTolerance.price(bad.price,"2.04"));
    }
    private GameLinesParser.Word line(String text, int top) { return new GameLinesParser.Word(text,80,top,600,top+20); }
    @Test public void rememberedNonEmailAccountMustMatchExactly() {
        assertEquals(LoginAccount.State.MATCH, LoginAccount.inspect(Arrays.asList(line("saved_username",305), line("x",305)), "saved_username"));
        assertEquals(LoginAccount.State.DIFFERENT, LoginAccount.inspect(Arrays.asList(line("other_user",305), line("x",305)), "saved_username"));
        assertEquals(LoginAccount.State.UNKNOWN, LoginAccount.inspect(Arrays.asList(line("unreadable",305)), "saved_username"));
        assertEquals(LoginAccount.State.EMPTY, LoginAccount.inspect(Arrays.asList(line("Username or email",305)), "saved_username"));
        assertEquals(LoginAccount.State.EMPTY, LoginAccount.inspect(Arrays.asList(line("Username",308),line("or",308),line("email",308),line("address",308)), "saved_username"));
    }
    @Test public void improvementsAndSideSpecificDeterioration() {
        assertTrue(ExecutionTolerance.line("SPREAD","HOME","-7","-6.5","0"));
        assertFalse(ExecutionTolerance.line("SPREAD","HOME","-7","-7.5","0"));
        assertTrue(ExecutionTolerance.line("SPREAD","AWAY","3.5","3","0.5"));
        assertFalse(ExecutionTolerance.line("SPREAD","AWAY","3.5","2.5","0.5"));
        assertTrue(ExecutionTolerance.line("TOTAL","OVER","165","164.5","0"));
        assertFalse(ExecutionTolerance.line("TOTAL","OVER","165","165.5","0"));
        assertTrue(ExecutionTolerance.line("TOTAL","UNDER","165","165.5","0"));
        assertFalse(ExecutionTolerance.line("TOTAL","UNDER","165","164.5","0"));
        assertFalse(ExecutionTolerance.line("TOTAL","OVER","165","165",""));
    }
    @Test public void clearRememberedAccountRequiresItsOwnUniqueControl() {
        GameLinesParser.Word x = new GameLinesParser.Word("X",577,308,600,330);
        assertNotNull(LoginAccount.clearControl(Arrays.asList(x,new GameLinesParser.Word("X",577,309,600,331))));
        assertNull(LoginAccount.clearControl(Arrays.asList(line("x",305))));
        assertNull(LoginAccount.clearControl(Arrays.asList(x,new GameLinesParser.Word("X",577,360,600,380))));
        assertNull(LoginAccount.clearControl(Arrays.asList(new GameLinesParser.Word("X",577,700,600,720))));
    }
    @Test public void secretEntryRequiresChromePasswordEditor() {
        assertTrue(SecretEditor.matches("com.android.chrome",0xe1));
        assertTrue(SecretEditor.matches("com.android.chrome",0x80081));
        assertFalse(SecretEditor.matches("com.android.chrome",1));
        assertFalse(SecretEditor.matches("com.other.app",0xe1));
    }
    @Test public void reservesAndAgeVariantsRemainDistinctEvenWithAliases() {
        for (String other : Arrays.asList("III","B","Academy","Youth"))
            assertFalse(EventIdentity.matchSide("Club II", "Club " + other, Collections.singletonMap("club ii","Club " + other)).markersAgree);
        assertEquals(EventIdentity.markers(EventIdentity.normalise("Club U-21")),EventIdentity.markers(EventIdentity.normalise("Club U21")));
        assertFalse(EventIdentity.matchSide("Club U-21","Club U23",Collections.emptyMap()).markersAgree);
    }
    @Test public void exactNamesCannotReplaceKnownEventContext() {
        EventIdentity.Event feed = new EventIdentity.Event("basketball","Boras Basket","Nassjo Basket","25 Sep 18:04","Sweden - Basketligan",false);
        EventIdentity.Event page = new EventIdentity.Event("basketball","Boras Basket","Nassjo Basket","25 Sep 18:04","Sweden Basketligan 25 Sep 18:04",true);
        assertTrue(EventIdentity.resolveVerified(feed,page,Collections.emptyMap(),false).accepted());
        assertFalse(EventIdentity.resolveVerified(feed,new EventIdentity.Event("basketball",page.home,page.away,null,page.competition,true),Collections.emptyMap(),false).accepted());
        assertFalse(EventIdentity.resolveVerified(feed,new EventIdentity.Event("basketball",page.home,page.away,page.kickoffUk,"Sweden Cup",true),Collections.emptyMap(),false).accepted());
    }
    @Test public void backgroundFixtureCannotAuthorizeDifferentSlip() {
        List<GameLinesParser.Word> realLayout = new ArrayList<>(Arrays.asList(
                line("Hapoel Tel Aviv vs Bayern Munich",390),line("Game Totals",1219),
                line("Hapoel Tel Aviv vs Bayern Munich",1253)));
        assertTrue(HeldSlipIdentity.matches(realLayout,"Hapoel Tel Aviv","Bayern Munich","TOTAL",1324));
        realLayout.set(2,line("Hapoel Tel Aviv vs Alba Berlin",1253));
        assertFalse(HeldSlipIdentity.matches(realLayout,"Hapoel Tel Aviv","Bayern Munich","TOTAL",1324));
        realLayout.set(2,line("Bayern Munich vs Hapoel Tel Aviv",1253));
        assertFalse(HeldSlipIdentity.matches(realLayout,"Hapoel Tel Aviv","Bayern Munich","TOTAL",1324));
        realLayout.set(2,line("Hapoel Tel Aviv vs Bayern Munich",1253));
        realLayout.set(1,line("1st Half Game Totals",1219));
        assertFalse(HeldSlipIdentity.matches(realLayout,"Hapoel Tel Aviv","Bayern Munich","TOTAL",1324));
    }
    @Test public void quoteMustComeFromSlipSelectionRow() {
        List<GameLinesParser.Word> lines=Arrays.asList(line("Under 173.5 1.83",800),line("Under 174.0 1.90",1180),line("Game Totals",1219));
        HeldSlipQuote q=HeldSlipQuote.read(lines,"Under","TOTAL",1324);
        assertNotNull(q);assertEquals("174.0",q.line);assertEquals("1.90",q.price);
        assertNull(HeldSlipQuote.read(lines,"Over","TOTAL",1324));
        assertNull(HeldSlipQuote.read(Arrays.asList(line("Under 173.5 1.83",800),line("Game Totals",1219)),"Under","TOTAL",1324));
    }
    @Test public void staleHoldAndFutureHoldCannotAuthorizePlacement() {
        assertTrue(HeldInstruction.fresh(1000,5000,126000));
        assertFalse(HeldInstruction.fresh(1000,5000,126001));
        assertFalse(HeldInstruction.fresh(1000,5000,5999));
        assertFalse(HeldInstruction.fresh(1000,-1,2000));
    }
}
