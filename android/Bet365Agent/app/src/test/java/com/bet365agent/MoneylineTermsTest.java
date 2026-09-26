package com.bet365agent;

import static org.junit.Assert.*;
import java.util.*;
import org.junit.Test;

public class MoneylineTermsTest {
    private GameLinesParser.Word row(String s, int top) { return new GameLinesParser.Word(s,80,top,600,top+20); }
    @Test public void basketballHasExactlyHomeAndAway() {
        assertTrue(MoneylineTerms.validSide("basketball","HOME"));
        assertTrue(MoneylineTerms.validSide("basketball","AWAY"));
        assertFalse(MoneylineTerms.validSide("basketball","DRAW"));
        assertFalse(MoneylineTerms.validSide("basketball","OVER"));
        assertTrue(MoneylineTerms.validSide("football","DRAW"));
    }
    @Test public void ownSlipRowHasPriceWithoutAnyHandicap() {
        // Named team and price from real stored ML feed 67969; pre-tap boundary values are test mutations.
        for (String price : Arrays.asList("2.25","2.13","2.12","3.00")) {
            List<GameLinesParser.Word> lines=Arrays.asList(row("Aguila San Miguel 1.57",850),row("San Salvador "+price,1180),row("Money Line",1219));
            HeldSlipQuote quote=HeldSlipQuote.read(lines,"San Salvador","MONEYLINE",1324);
            assertNotNull(quote);assertEquals("",quote.line);assertEquals(price,quote.price);
            assertEquals(!price.equals("2.12"),ExecutionTolerance.price(quote.price,"2.13"));
            assertNull(HeldSlipQuote.read(lines,"Aguila San Miguel","MONEYLINE",1324));
        }
        assertNull(HeldSlipQuote.read(Arrays.asList(row("San Salvador -1.5 2.25",1180),row("Money Line",1219)),"San Salvador","MONEYLINE",1324));
    }
    @Test public void priceOnlyReceiptCannotBorrowHandicapOpponentOrPretapTerms() {
        assertEquals("2.13",MoneylineTerms.receiptPrice(Arrays.asList("Bet Placed","San Salvador 2.13"),"San Salvador"));
        assertNull(MoneylineTerms.receiptPrice(Arrays.asList("Aguila San Miguel 2.13"),"San Salvador"));
        assertNull(MoneylineTerms.receiptPrice(Arrays.asList("San Salvador -1.5 2.13"),"San Salvador"));
        assertNull(MoneylineTerms.receiptPrice(Arrays.asList("San Salvador 2.13","San Salvador 2.25"),"San Salvador"));
        assertNull(MoneylineTerms.receiptPrice(Arrays.asList("San Salvador 1.00"),"San Salvador"));
    }
}
