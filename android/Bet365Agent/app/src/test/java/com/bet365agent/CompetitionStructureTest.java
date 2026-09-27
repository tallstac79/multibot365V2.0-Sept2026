package com.bet365agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.util.Collections;
import org.junit.Test;

/** Structural competition identity: real naming differences pass, genuine competition conflicts fail closed. */
public class CompetitionStructureTest {
    private static void compatible(String feed, String country, String page) {
        assertNull(feed + " / " + page + " : " + CompetitionStructure.describe(feed, page), CompetitionStructure.conflict(feed, country, page));
    }

    private static void conflicting(String feed, String country, String page) {
        assertNotNull(feed + " / " + page + " should conflict", CompetitionStructure.conflict(feed, country, page));
    }

    @Test public void realNamingDifferencesFrom27Sep2026() {
        compatible("Liga 1 Women", "Poland", "Poland 1 Liga Women 27 Sep 12:00");                 // country prefix, word order
        compatible("NB 2 Women", "Hungary", "Hungary NBII Women 27 Sep 16:30");                    // glued roman tier
        compatible("Tercera Division", "Spain", "Spain Tercera Group 18• 27 Sep 16:30");           // bookmaker group
        compatible("Segunda Federacion", "Spain", "Spain Segunda Division RFEF Group1 27 Sep 16:00"); // RFEF / federation
        compatible("4th Liga", "Poland", "Poland IV Liga • 27 Sep 15:00");                         // 4th = IV
        compatible("2. Liga Women", "Czech Republic", "Czechia Div 2 Women 27 Sep 13:30");         // country spelling, Div
        compatible("1. Liga Women", "Czech Republic", "Czechia Division 1 Women");
        compatible("Division 1 Women", "Belgium", "Belgium Div 1 Women 27 Sep 14:00");
        compatible("Super League Women", "Turkey", "Turkiye TKBSL Women 27 Sep 12:00");            // brand name, Turkiye
        compatible("Super League", "Turkey", "Turkiye BSL 27 Sep 16:00");
        compatible("NPFL", "Nigeria", "Nigeria Premier League 27 Sep 16:00");
        compatible("SB League", "Switzerland", "Switzerland LNA 27 Sep 15:00");
        compatible("Adriatic League Women", null, "Adriatic WABA Women 27 Sep 15:00");
        compatible("Premier Division", "Iraq", "Iraq Premier League 27 Sep 13:45");
        compatible("1st League", "Bosnia and Herzegovina", "Bosnia & Herzegovina 1st League27 Sep 15:00"); // glued date
        compatible("Kvindebasketligaen", "Denmark", "Denmark Basketligaen Women 27 Sep 16:30");    // Danish women's
        compatible("Division 2", "Sweden", "Sweden 2.div Norrland 27 Sep 12:00");
        compatible("Kakkonen Group C", "Finland", "Finland Kakkonen Group C");
        compatible("B League", "Japan", "Japan B League 1 • 25 Sep 10:35");
        compatible("B2 League", "Japan", "Japan B League 2 • 25 Sep 10:35");
        compatible("National League Cup Women", "England", "England FA National League Cup Women 27 Sep 15:00");
        compatible("Super Cup", "Poland", "Poland Super Cup • 27 Sep 16:30");
        compatible("Serie A", "Italy", "Italy Serie A");
    }

    @Test public void genuineConflictsStillFailClosed() {
        conflicting("Liga 1", "Poland", "Poland 1 Liga Women");                    // gender
        conflicting("Liga 1 Women", "Poland", "Poland 1 Liga");
        conflicting("Liga 1 Women", "Poland", "Poland 2 Liga Women");              // tier
        conflicting("NB 1 Women", "Hungary", "Hungary NBII Women");
        conflicting("Premier League", "England", "England Premier League 2");
        conflicting("4th Liga", "Poland", "Poland III Liga");
        conflicting("Segunda Federacion", "Spain", "Spain Tercera Federacion Group 5");
        conflicting("Segunda Division", "Spain", "Spain Segunda Division RFEF Group 1"); // LaLiga2 is not the RFEF tier
        conflicting("Serie A", "Italy", "Italy Serie B");                           // tier letter
        conflicting("Primera Division", "Chile", "Chile Primera B");
        conflicting("Premier League", "England", "England Premier League U21");     // age
        conflicting("Primavera 1", "Italy", "Italy Serie A");
        conflicting("Liga ACB", "Spain", "Spain Liga ACB Youth");
        conflicting("Premier League", "England", "England Premier League Cup");      // cup vs league
        conflicting("KBL", "Korea", "Club Friendlies");                              // friendly vs competitive
        conflicting("Liga 1 Women", "Poland", "Romania Liga 1 Women");               // country
        conflicting("Super League", "Turkey", "Greece Super League");
        conflicting("", "Poland", "Poland 1 Liga Women");                            // unknown
        conflicting("Liga 1 Women", "Poland", "");
    }

    @Test public void onlyAnAnchoredPageGetsTheStructuralMatch() {
        EventIdentity.Event feed = new EventIdentity.Event("football", "CD Torrijos", "CD Quintanar del Rey", "27 Sep 16:30", "Tercera Division", false);
        EventIdentity.Event anchored = new EventIdentity.Event("football", "CD Torrijos", "CD Quintanar del Rey", "27 Sep 16:30", "Spain Tercera Group 18• 27 Sep 16:30", true);
        EventIdentity.Event searched = new EventIdentity.Event("football", "CD Torrijos", "CD Quintanar del Rey", "27 Sep 16:30", "Spain Tercera Group 18• 27 Sep 16:30", false);
        EventIdentity.Result a = EventIdentity.resolveVerified(feed, anchored, Collections.emptyMap(), false, "Spain");
        assertTrue(a.reason, a.accepted());
        assertTrue(String.valueOf(a.evidence.get("competition_match")).startsWith("structural_compatible"));
        assertFalse(EventIdentity.resolveVerified(feed, searched, Collections.emptyMap(), false, "Spain").accepted());
        // a structural conflict on an anchored page still fails closed, and says why
        EventIdentity.Event wrongTier = new EventIdentity.Event("football", "CD Torrijos", "CD Quintanar del Rey", "27 Sep 16:30", "Spain Segunda Division RFEF Group 5", true);
        EventIdentity.Result w = EventIdentity.resolveVerified(feed, wrongTier, Collections.emptyMap(), false, "Spain");
        assertFalse(w.accepted());
        assertTrue(String.valueOf(w.evidence.get("competition_match")).contains("structural conflict"));
        // kick-off still required
        EventIdentity.Event late = new EventIdentity.Event("football", "CD Torrijos", "CD Quintanar del Rey", "27 Sep 18:30", "Spain Tercera Group 18", true);
        assertFalse(EventIdentity.resolveVerified(feed, late, Collections.emptyMap(), false, "Spain").accepted());
    }

    @Test public void gluedDateIsStripped() {
        assertEquals("bosnia herzegovina 1st league", EventIdentity.competitionKey("Bosnia & Herzegovina 1st League27 Sep 15:00"));
    }
}
