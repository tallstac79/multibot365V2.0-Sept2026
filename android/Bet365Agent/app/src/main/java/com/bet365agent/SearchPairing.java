package com.bet365agent;

/**
 * Search-result pairing key (pure Java; SearchPairingTest). Bet365 groups each search hit under a heading row
 * "Vellaznimi vs KB Prishtina >" above the event row itself; OCR reads the chevron as ")" (27 Sep 2026), so the raw
 * keys "vellaznimi|kb prishtina)" and "vellaznimi|kb prishtina" made ONE event look like two and the Search fallback
 * refused it as AMBIGUOUS_FIXTURE. The key uses EventIdentity.normalise (punctuation dropped, words and protected markers
 * kept: "(W)" still separates a women's event). The opened event page is still verified by kick-off and competition.
 */
final class SearchPairing {
    private SearchPairing() {}

    static String key(String home, String away) {
        return EventIdentity.normalise(home) + "|" + EventIdentity.normalise(away);
    }

    /** A row whose names carry OCR punctuation at the edges (a heading's chevron) is the weaker duplicate. */
    static boolean cleaner(String home, String away, String otherHome, String otherAway) {
        return artifacts(home) + artifacts(away) < artifacts(otherHome) + artifacts(otherAway);
    }

    private static int artifacts(String name) {
        String t = name == null ? "" : name.trim();
        int n = 0;
        if (!t.isEmpty() && !Character.isLetterOrDigit(t.charAt(t.length() - 1)) && !t.endsWith("(W)")) n++;
        if (!t.isEmpty() && !Character.isLetterOrDigit(t.charAt(0))) n++;
        return n;
    }
}
