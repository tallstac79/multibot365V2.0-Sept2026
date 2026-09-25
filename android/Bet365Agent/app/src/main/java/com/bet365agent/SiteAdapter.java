package com.bet365agent;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import android.graphics.Rect;
import org.json.JSONObject;

/** Interface semantics only. Implementations own navigation, labels, parsing and layout rules. */
interface SiteAdapter {
    CompletableFuture<Void> open_home();
    CompletableFuture<Void> ensure_session();
    CompletableFuture<Void> open_search();
    CompletableFuture<Void> enter_query(String query);
    CompletableFuture<Fixture> discover_fixture();
    CompletableFuture<Void> select_fixture(Fixture fixture);
    CompletableFuture<Void> verify_event(Fixture fixture);
    CompletableFuture<List<Selection>> discover_markets();
    CompletableFuture<Selection> read_selection(List<Selection> markets, String market, String side, String line);
    CompletableFuture<String> read_line(Selection selection);
    CompletableFuture<String> read_price(Selection selection);
    CompletableFuture<Void> open_selection(Selection selection);
    CompletableFuture<Void> enter_stake(String stake);
    CompletableFuture<Void> verify_final_state(Fixture fixture, Selection selection, String stake);
    /** Locate Place Bet, record COMPLETE_EXECUTION_READY + prepared gesture; NEVER dispatches. */
    CompletableFuture<Void> prepare_complete_execution(Fixture fixture, Selection selection, String stake, String minimumPrice);
    /** Remove this run's selection from the betslip (READY/prepare runs), so the next run is still a single.
     *  Only the remove (X) icon on the selection's own line is tapped. */
    default CompletableFuture<Void> clear_betslip(Selection selection) { return CompletableFuture.completedFuture(null); }
    /** The instruction's target (market/side/line): lets the adapter skip extra reads of unrelated markets. */
    default void set_target(String market, String side, String line) {}
    /** Aliases supplied with the instruction (feed name -> bookmaker name), from the backend's registry/cache. */
    default void set_aliases(java.util.Map<String, String> aliases) {}
    /** The backend established the competition as women's: a missing "(W)" on a feed name may be supplied (resolver rule). */
    default void set_competition_women(boolean women) {}
    /** Open the alert's exact event link and verify it (sport, both teams, kick-off). Null = not usable: search instead. */
    default CompletableFuture<Fixture> open_event_direct(String url, String query, String kickoffUtc) { return CompletableFuture.completedFuture(null); }
    /** Dispatch the prepared Place Bet gesture for real. */
    CompletableFuture<Void> place_bet(Fixture fixture, Selection selection, String stake);

    final class Fixture {
        final String code, home, away, competition;
        final Rect bounds;
        Fixture(String code, String home, String away, String competition, Rect bounds) {
            this.code=code; this.home=home; this.away=away; this.competition=competition; this.bounds=new Rect(bounds);
        }
        String name() { return home + " v " + away; }
        boolean same(Fixture other) { return code.equals(other.code) && name().equals(other.name()) && competition.equals(other.competition); }
        JSONObject json() { return CoordinatorAgent.object("code",code,"home",home,"away",away,"fixture_name",name(),"exact_fixture_text","Home "+home+"\nAway "+away,"competition",competition,"bounds",VisualSession.bounds(bounds)); }
    }
    final class Selection {
        final String market, side, line, price, availability, name;
        final Rect bounds;
        Selection(String market, String side, String line, String price, String availability, Rect bounds) {
            this(market, side, line, price, availability, bounds, "");
        }
        Selection(String market, String side, String line, String price, String availability, Rect bounds, String name) {
            this.market=market; this.side=side; this.line=line; this.price=price; this.availability=availability; this.bounds=new Rect(bounds);
            this.name = name == null ? "" : name;
        }
        boolean identity(Selection other) { return market.equals(other.market) && side.equals(other.side) && line.equals(other.line); }
        JSONObject json() { return CoordinatorAgent.object("market",market,"side",side,"line",line,"price",price,"availability",availability,"selection_role",side,"selection_name",name,"bounds",VisualSession.bounds(bounds)); }
    }
    final class Failure extends RuntimeException {
        final String stage;
        Failure(String stage, String detail) { super(detail); this.stage=stage; }
    }
}
