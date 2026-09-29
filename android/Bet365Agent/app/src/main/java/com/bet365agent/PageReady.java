package com.bet365agent;

import java.util.Collection;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TreeSet;

/**
 * "Is this the page we navigated to, fully drawn?" decisions for the hot path (pure Java; SpeedPathTest).
 *
 * The phone used to wait a fixed 1.2 s + 2.2 s after opening an event link and a fixed ~1.9 s after every tab tap before
 * it looked at the screen (29 Sep 2026 speed work: 3.4 s of the ~4.2 s median OPEN_HOME and ~4 s of every football tab
 * change were waiting). It now looks at once and keeps looking until the page itself says it is ready. These rules decide
 * "ready" and can only ever DELAY the next step, never accept anything: identity, line, price and stake are decided by the
 * same checks as before on the frame that is finally used.
 *
 * The one hazard of looking early is a STALE page: after a failed job the phone can still be showing the previous event
 * when the next link is opened, and a frame of that page must not be mistaken for the new one (it would then be refused as
 * the wrong event where the old fixed wait let the new page load first). Hence two tiers.
 */
final class PageReady {
    private PageReady() {}

    /** Weaker evidence (a shared word, or a matching kick-off alone) is trusted only once the page has had this long to
     *  replace any previous one. Measured: a new event's header is drawn 3.6-5 s after the link is opened (the old schedule
     *  looked first at 3.4 s), so 5 s covers a page swap; strong evidence needs no such wait. */
    static final long LOOSE_AFTER_MS = 5_000;

    /**
     * An event page is ready when its header names two teams and it is THIS event's page:
     *  - strong (at once): a team on the page is identified as one of the alert's teams (EventIdentity.compareTokens, which
     *    ignores the protected markers that identity judges later - "(W)", "U21" - under the alert's own names and the
     *    bookmaker aliases it supplied) AND either the kick-off is shown and compatible with the alert's, or - kick-off not
     *    shown - BOTH page teams are identified, in the alert's order;
     *  - loose (after LOOSE_AFTER_MS): the header shares a distinctive word with the alert's names, or its kick-off equals
     *    the alert's.
     * A page whose kick-off is shown and incompatible is never strong; it is kept polling until the caller's cap, after which
     * the ordinary identity check judges (and refuses) whatever is on screen.
     */
    static boolean eventReady(List<String> header, String[] teams, Collection<String> homeNames, Collection<String> awayNames,
                              String wantUk, long waitedMs) {
        if (teams == null) return false;
        String shown = EventPage.kickoffText(header);
        boolean koKnown = wantUk != null && shown != null;
        String ko = koKnown ? EventIdentity.kickoffMatch(wantUk, shown) : "unknown";
        boolean koCompatible = ko.equals("exact") || ko.startsWith("within_tolerance") || ko.startsWith("same_instant");
        boolean home = identified(teams[0], homeNames) || identified(teams[1], homeNames);
        boolean away = identified(teams[0], awayNames) || identified(teams[1], awayNames);
        boolean inOrder = identified(teams[0], homeNames) && identified(teams[1], awayNames);
        if (koKnown && koCompatible && (home || away)) return true;
        if (!koKnown && inOrder) return true;
        if (waitedMs < LOOSE_AFTER_MS) return false;
        if (ko.equals("exact")) return true;
        return shares(teams[0], homeNames) || shares(teams[1], homeNames) || shares(teams[0], awayNames) || shares(teams[1], awayNames);
    }

    /** The page team is the alert team under any of its names: the same distinctive tokens, an abbreviation or a naming variant. */
    private static boolean identified(String pageName, Collection<String> feedNames) {
        if (pageName == null || feedNames == null) return false;
        String page = EventIdentity.normalise(pageName);
        for (String name : feedNames) {
            if (name == null || name.isEmpty()) continue;
            if (EventIdentity.compareTokens(EventIdentity.normalise(name), page).level.ordinal() >= EventIdentity.Level.VARIANT.ordinal()) return true;
        }
        return false;
    }

    private static boolean shares(String pageName, Collection<String> feedNames) {
        Set<String> page = words(pageName);
        if (page.isEmpty() || feedNames == null) return false;
        for (String name : feedNames) {
            Set<String> mine = words(name);
            mine.retainAll(page);
            if (!mine.isEmpty()) return true;
        }
        return false;
    }

    private static Set<String> words(String name) {
        Set<String> out = new TreeSet<>();
        if (name == null) return out;
        for (String t : EventIdentity.normalise(name).split(" ")) if (t.length() >= 3) out.add(t.toLowerCase(Locale.US));
        return out;
    }

    /**
     * A football market tab is ready when its OWN section is drawn with its quotes (the tab tap returns at once and the
     * page settles over a fraction of a second, not a fixed 1.9 s). "goals" and "popular" show the same main total row,
     * so they also require a short settle after the tap: a frame still showing the previous tab must not count.
     */
    static boolean footballTabReady(String prefix, FootballMarkets.Result r, long waitedMs) {
        boolean spread = has(r, "SPREAD"), total = has(r, "TOTAL");
        switch (prefix) {
            case "asia": return r.asianHandicap && spread;
            case "goals": return r.goalsOverUnder && total && waitedMs >= 400;
            case "popular": return (r.goalsOverUnder || r.fullTimeResult) && !r.asianHandicap && waitedMs >= 250;
            default: return !r.cells.isEmpty() && waitedMs >= 400;
        }
    }

    private static boolean has(FootballMarkets.Result r, String market) {
        for (FootballMarkets.Cell c : r.cells) if (c.market.equals(market)) return true;
        return false;
    }
}
