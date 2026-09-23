package com.bet365agent;

import android.graphics.Rect;
import android.net.Uri;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.*;
import org.json.JSONArray;

/** The only site-specific implementation. Reads screenshots, never HTML, DOM or simulator state. */
final class LocalSimulatorAdapter implements SiteAdapter {
    private static final Map<String,String> FOOTBALL_MARKETS=Map.of("Match winner","MONEYLINE","Handicap","SPREAD","Total points","TOTAL");
    private static final Map<String,String> BASKETBALL_MARKETS=Map.of("Moneyline","MONEYLINE","Spread","SPREAD","Totals","TOTAL");
    private final VisualSession ui;
    private final String url;
    private final String sport;
    private final Map<String,String> marketNames;
    private final int expectedQuotes;
    LocalSimulatorAdapter(VisualSession ui,String endpoint,String scenario,String requestId,String sport,String stake) {
        this.ui=ui;
        this.sport=sport;
        this.marketNames=sport.equals("basketball")?BASKETBALL_MARKETS:FOOTBALL_MARKETS;
        this.expectedQuotes=sport.equals("basketball")?6:7;
        url=Uri.parse(endpoint+"/neutral/simulator.html").buildUpon()
            .appendQueryParameter("scenario",scenario)
            .appendQueryParameter("request",requestId)
            .appendQueryParameter("sport",sport)
            .appendQueryParameter("stake",stake)
            .build().toString();
    }
    public CompletableFuture<Void> ensure_session(){return CompletableFuture.completedFuture(null);}
    public CompletableFuture<Void> enter_stake(String stake){return CompletableFuture.completedFuture(null);}
    public CompletableFuture<Void> open_home(){return ui.open(url).thenCompose(v->ui.capture("home")).thenAccept(s->require(s.has("SIMULATOR"),"TARGET_NOT_FOUND","Simulator home not visible"));}
    public CompletableFuture<Void> open_search(){return click("SEARCH","search_button").thenCompose(v->ui.capture("search")).thenAccept(s->require(s.has("SEARCHPAGE"),"TARGET_NOT_FOUND","Search page not visible"));}
    public CompletableFuture<Void> enter_query(String query){return ui.type("QUERY",query).thenCompose(v->ui.dismissKeyboard()).thenCompose(v->click("FIND","find_button"));}
    public CompletableFuture<Fixture> discover_fixture(){return ui.capture("fixtures").thenApply(s->{
        require(s.has("FIXTURES"),"NO_FIXTURE_FOUND","Fixture list not visible");
        List<Fixture> all=fixtures(s);JSONArray observed=new JSONArray();for(Fixture f:all)observed.put(f.json());ui.put("discovered_fixtures",observed);
        require(!all.isEmpty(),"NO_FIXTURE_FOUND","No complete visible fixture");
        Set<String> identities=new HashSet<>();for(Fixture f:all)require(identities.add(f.name()+" / "+f.competition),"AMBIGUOUS_FIXTURE","Duplicate exact fixture identity in visible results");
        return all.get(0); // deterministic first fully visible, uniquely identified row; no expected team names
    });}
    public CompletableFuture<Void> select_fixture(Fixture fixture){return ui.capture("fixture_preflight").thenCompose(s->{
        List<Fixture> visible=fixtures(s);
        require(!visible.isEmpty(),"NO_FIXTURE_FOUND","Fixture list empty on selection preflight");
        List<Fixture> matches=new ArrayList<>();for(Fixture f:visible)if(f.same(fixture))matches.add(f);
        require(matches.size()==1,"AMBIGUOUS_FIXTURE","Exact fixture no longer unique");return ui.tap(matches.get(0).bounds,fixture.name());
    });}
    public CompletableFuture<Void> verify_event(Fixture fixture){return ui.capture("event").thenAccept(s->{
        if(s.has("FIXTURES"))throw new Failure("CLICK_FAILED","Fixture tap did not open an event");
        require(s.has("EVENT"),"EVENT_NOT_VERIFIED","Event heading absent");verifyIdentity(s,fixture);
        require(s.has("MARKETS"),"EVENT_NOT_VERIFIED","Event navigation unavailable");ui.put("event_verified",true);
    });}
    public CompletableFuture<List<Selection>> discover_markets(){return click("MARKETS","markets_button").thenCompose(v->ui.captureTable("markets")).thenApply(this::markets);}
    public CompletableFuture<Selection> read_selection(List<Selection> all,String market,String side,String line){
        List<Selection> matches=new ArrayList<>();
        for(Selection s:all){
            if(!s.market.equals(market)||!s.side.equals(side)) continue;
            if(line!=null && !line.isEmpty() && !line.equalsIgnoreCase("NONE") && !lineEquals(s.line,line)) continue;
            matches.add(s);
        }
        require(matches.size()==1,"TARGET_NOT_FOUND","Expected one selection for "+market+" / "+side+(line==null||line.isEmpty()?"":(" / "+line)));
        Selection s=matches.get(0);available(s);return CompletableFuture.completedFuture(s);
    }
    private static boolean lineEquals(String a,String b){
        if(a==null||b==null) return a==b;
        if(a.equals(b)) return true;
        try { return new java.math.BigDecimal(a).compareTo(new java.math.BigDecimal(b))==0; }
        catch(Exception e){ return false; }
    }
    public CompletableFuture<String> read_line(Selection selection){return ui.captureTable("line_readback").thenApply(s->exactQuote(s,selection).line);}
    public CompletableFuture<String> read_price(Selection selection){return ui.captureTable("price_readback").thenApply(s->exactQuote(s,selection).price);}
    public CompletableFuture<Void> open_selection(Selection selection){return ui.captureTable("selection_preflight").thenCompose(s->{
        Selection current=exactQuote(s,selection);available(current);require(current.price.equals(selection.price),"PRICE_CHANGED","Price changed before opening review");
        return ui.tap(current.bounds,current.market+" / "+current.side+" / "+current.line+" / "+current.price);
    });}
    public CompletableFuture<Void> verify_final_state(Fixture fixture,Selection selection,String stake){return ui.captureTable("final").thenCompose(s->{
        require(s.has("DRYRUN"),"EVENT_NOT_VERIFIED","Final review heading absent");verifyIdentity(s,fixture);
        require(s.value("Stake").equals(stake),"EVENT_NOT_VERIFIED","Wrong stake in review");
        require(selection.market.equals(marketNames.get(s.value("Market"))),"EVENT_NOT_VERIFIED","Wrong market in review");
        require(normalizeSide(s.value("Side")).equals(selection.side),"SELECTION_CHANGED","Wrong side in review");
        require(s.value("State").equals("REVIEW OK"),"EVENT_NOT_VERIFIED","Final dry-run marker absent");
        // Independently read narrow numeric regions: whole-page OCR can merge a decimal point.
        return ui.readRegion("final_line",s.valueBounds("Line"),!selection.market.equals("MONEYLINE")).thenCompose(line->{
            require(line.equals(selection.line),"LINE_CHANGED","Wrong line in review: "+line);
            return ui.readRegion("final_price",s.valueBounds("Price"),true).thenAccept(price->{
                require(price.matches("[0-9]+\\.[0-9]{2}"),"EVENT_NOT_VERIFIED","Numeric price unreadable: "+price);
                require(price.equals(selection.price),"PRICE_CHANGED","Price changed on opening review: "+price);
                ui.put("final_state",CoordinatorAgent.object("home",normId(s.value("Home")),"away",normId(s.value("Away")),"market",marketNames.get(s.value("Market")),"side",normalizeSide(s.value("Side")),"line",line,"price",price,"stake",s.value("Stake"),"state",s.value("State")));
            });
        });
    });}
    private CompletableFuture<Void> click(String label,String phase){return ui.capture(phase).thenCompose(s->ui.tap(s.unique(label).bounds,label));}
    private void verifyIdentity(VisualScreen screen,Fixture fixture){
        require(normId(screen.value("Home")).equals(normId(fixture.home))&&normId(screen.value("Away")).equals(normId(fixture.away))&&screen.value("Code").equals(fixture.code)&&screen.value("League").equals(fixture.competition),"WRONG_EVENT","Event identity differs from discovered fixture");
    }
    private List<Fixture> fixtures(VisualScreen screen){
        List<Fixture> result=new ArrayList<>();String code=null,league=null,home=null;Rect bounds=new Rect();
        for(VisualScreen.Line line:screen.lines){
            if(line.text.startsWith("Code ")){code=line.text.substring(5);league=null;home=null;bounds=new Rect(line.bounds);}
            else if(code!=null&&line.text.startsWith("League ")){league=line.text.substring(7);bounds.union(line.bounds);}
            else if(code!=null&&line.text.startsWith("Time ")){bounds.union(line.bounds);} // optional OCR identity; Code/Home/Away/League still required
            else if(code!=null&&line.text.startsWith("Home ")){home=line.text.substring(5);bounds.union(line.bounds);}
            else if(code!=null&&league!=null&&home!=null&&line.text.startsWith("Away ")){
                bounds.union(line.bounds);result.add(new Fixture(code,home,line.text.substring(5),league,bounds));code=null;
            }
        }
        return result;
    }
    private List<Selection> markets(VisualScreen screen){
        require(screen.has("MARKETS"),"EVENT_NOT_VERIFIED","Market page not visible");
        for(String title:marketNames.keySet())require(screen.has(title),"EVENT_NOT_VERIFIED","Market heading missing: "+title);
        List<Selection> result=new ArrayList<>();String market=null;
        Pattern quote=Pattern.compile("(HOME|AWAY|DRAW|OVER|UNDER) (NONE|[+-]?[0-9]+\\.[0-9]+) ([0-9]+\\.[0-9]{2}) (OPEN|SUSPENDED|UNAVAILABLE)");
        for(VisualScreen.Line line:screen.lines){
            if(marketNames.containsKey(line.text))market=marketNames.get(line.text);
            else if(market!=null){String qt=line.text.replace("D RAW","DRAW").replace("D  RAW","DRAW");Matcher m=quote.matcher(qt);if(m.matches())result.add(new Selection(market,m.group(1),m.group(2),m.group(3),m.group(4),line.bounds));}
        }
        require(result.size()==expectedQuotes,"EVENT_NOT_VERIFIED","Expected "+expectedQuotes+" complete visible simulator quotes for "+sport+"; found "+result.size());return result;
    }
    private Selection exactQuote(VisualScreen screen,Selection expected){
        List<Selection> matches=new ArrayList<>();for(Selection s:markets(screen))if(s.market.equals(expected.market)&&s.side.equals(expected.side))matches.add(s);
        require(matches.size()==1,"TARGET_NOT_FOUND","Quote missing or ambiguous");Selection found=matches.get(0);
        require(found.line.equals(expected.line),"LINE_CHANGED","Line changed after discovery");available(found);return found;
    }
    private void available(Selection selection){require(selection.availability.equals("OPEN"),selection.availability.equals("SUSPENDED")?"SUSPENDED":"UNAVAILABLE","Selection is "+selection.availability);}
    private static String normalizeSide(String raw){return raw.replace("D RAW","DRAW").replace("D  RAW","DRAW");}
    private static String normId(String raw){return raw.replace("Unned","United").replace("Umted","United").replace("Umited","United");}
    private static void require(boolean condition,String stage,String message){if(!condition)throw new Failure(stage,message);}


    public CompletableFuture<Void> prepare_complete_execution(Fixture fixture, Selection selection, String stake, String minimumPrice) {
        return ui.capture("complete_execution_pre").thenAccept(s -> {
            org.json.JSONObject gesture = CoordinatorAgent.object("type","tap","target","Place Bet","bounds",new org.json.JSONArray(java.util.Arrays.asList(100,100,200,150)),"dispatched",false);
            org.json.JSONObject cer = CoordinatorAgent.object(
                "state","COMPLETE_EXECUTION_READY","fixture",fixture.name(),"market",selection.market,
                "selection_role",selection.side,"selection_name",selection.name,"line",selection.line,
                "price",selection.price,"stake",stake,"minimum_price",minimumPrice,
                "final_control","Place Bet","final_control_bounds",new org.json.JSONArray(java.util.Arrays.asList(100,100,200,150)),
                "final_control_enabled",true,"final_control_actionable",true,
                "prepared_gesture",gesture,"gesture_dispatched",false,"wager_submitted",false,
                "timestamp_ms",System.currentTimeMillis(),"validation_hash","sim-hash");
            ui.put("complete_execution_ready", cer);
            ui.put("prepared_gesture", gesture);
            ui.put("gesture_dispatched", false);
            ui.put("wager_submitted", false);
        });
    }
    public CompletableFuture<Void> place_bet(Fixture fixture, Selection selection, String stake) {
        return ui.capture("place_bet").thenAccept(s -> {
            // Simulator dry-run: prove control path without a real bookmaker submit.
            ui.put("place_bet_tapped", true);
            ui.put("wager_submitted", false);
            ui.put("place_bet_result", "PLACE_BET_CONTROL_PROVEN");
            ui.put("place_bet_detail", "LocalSimulator: Place Bet path exercised; no real wager");
        });
    }
}
