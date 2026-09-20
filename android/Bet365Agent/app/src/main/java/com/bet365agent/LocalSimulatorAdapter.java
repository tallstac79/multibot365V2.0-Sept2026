package com.bet365agent;

import android.graphics.Rect;
import android.net.Uri;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.*;
import org.json.JSONArray;

/** The only site-specific implementation. Reads screenshots, never HTML, DOM or simulator state. */
final class LocalSimulatorAdapter implements SiteAdapter {
    private static final Map<String,String> MARKET_NAMES=Map.of("Match winner","MONEYLINE","Handicap","SPREAD","Total points","TOTAL");
    private final VisualSession ui;
    private final String url;
    LocalSimulatorAdapter(VisualSession ui,String endpoint,String scenario,String requestId) {
        this.ui=ui;
        url=Uri.parse(endpoint+"/neutral/simulator.html").buildUpon().appendQueryParameter("scenario",scenario).appendQueryParameter("request",requestId).build().toString();
    }
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
        List<Fixture> matches=new ArrayList<>();for(Fixture f:fixtures(s))if(f.same(fixture))matches.add(f);
        require(matches.size()==1,"AMBIGUOUS_FIXTURE","Exact fixture no longer unique");return ui.tap(matches.get(0).bounds,fixture.name());
    });}
    public CompletableFuture<Void> verify_event(Fixture fixture){return ui.capture("event").thenAccept(s->{
        if(s.has("FIXTURES"))throw new Failure("CLICK_FAILED","Fixture tap did not open an event");
        require(s.has("EVENT"),"EVENT_NOT_VERIFIED","Event heading absent");verifyIdentity(s,fixture);
        require(s.has("MARKETS"),"EVENT_NOT_VERIFIED","Event navigation unavailable");ui.put("event_verified",true);
    });}
    public CompletableFuture<List<Selection>> discover_markets(){return click("MARKETS","markets_button").thenCompose(v->ui.captureTable("markets")).thenApply(this::markets);}
    public CompletableFuture<Selection> read_selection(List<Selection> all,String market,String side){
        List<Selection> matches=new ArrayList<>();for(Selection s:all)if(s.market.equals(market)&&s.side.equals(side))matches.add(s);
        require(matches.size()==1,"TARGET_NOT_FOUND","Expected one selection for "+market+" / "+side);
        Selection s=matches.get(0);available(s);return CompletableFuture.completedFuture(s);
    }
    public CompletableFuture<String> read_line(Selection selection){return ui.captureTable("line_readback").thenApply(s->exactQuote(s,selection).line);}
    public CompletableFuture<String> read_price(Selection selection){return ui.captureTable("price_readback").thenApply(s->exactQuote(s,selection).price);}
    public CompletableFuture<Void> open_selection(Selection selection){return ui.captureTable("selection_preflight").thenCompose(s->{
        Selection current=exactQuote(s,selection);available(current);require(current.price.equals(selection.price),"PRICE_CHANGED","Price changed before opening review");
        return ui.tap(current.bounds,current.market+" / "+current.side+" / "+current.line+" / "+current.price);
    });}
    public CompletableFuture<Void> verify_final_state(Fixture fixture,Selection selection){return ui.captureTable("final").thenCompose(s->{
        require(s.has("DRYRUN"),"EVENT_NOT_VERIFIED","Final review heading absent");verifyIdentity(s,fixture);
        require(selection.market.equals(MARKET_NAMES.get(s.value("Market"))),"EVENT_NOT_VERIFIED","Wrong market in review");
        require(s.value("Side").equals(selection.side),"SELECTION_CHANGED","Wrong side in review");
        require(s.value("State").equals("REVIEWONLY"),"EVENT_NOT_VERIFIED","Final dry-run marker absent");
        // Independently read narrow numeric regions: whole-page OCR can merge a decimal point.
        return ui.readRegion("final_line",s.valueBounds("Line"),!selection.market.equals("MONEYLINE")).thenCompose(line->{
            require(line.equals(selection.line),"LINE_CHANGED","Wrong line in review: "+line);
            return ui.readRegion("final_price",s.valueBounds("Price"),true).thenAccept(price->{
                require(price.matches("[0-9]+\\.[0-9]{2}"),"EVENT_NOT_VERIFIED","Numeric price unreadable: "+price);
                require(price.equals(selection.price),"PRICE_CHANGED","Price changed on opening review: "+price);
                ui.put("final_state",CoordinatorAgent.object("home",s.value("Home"),"away",s.value("Away"),"market",MARKET_NAMES.get(s.value("Market")),"side",s.value("Side"),"line",line,"price",price,"state",s.value("State")));
            });
        });
    });}
    private CompletableFuture<Void> click(String label,String phase){return ui.capture(phase).thenCompose(s->ui.tap(s.unique(label).bounds,label));}
    private void verifyIdentity(VisualScreen screen,Fixture fixture){
        require(screen.value("Home").equals(fixture.home)&&screen.value("Away").equals(fixture.away)&&screen.value("Code").equals(fixture.code)&&screen.value("League").equals(fixture.competition),"WRONG_EVENT","Event identity differs from discovered fixture");
    }
    private List<Fixture> fixtures(VisualScreen screen){
        List<Fixture> result=new ArrayList<>();String code=null,league=null,home=null;Rect bounds=new Rect();
        for(VisualScreen.Line line:screen.lines){
            if(line.text.startsWith("Code ")){code=line.text.substring(5);league=null;home=null;bounds=new Rect(line.bounds);}
            else if(code!=null&&line.text.startsWith("League ")){league=line.text.substring(7);bounds.union(line.bounds);}
            else if(code!=null&&line.text.startsWith("Home ")){home=line.text.substring(5);bounds.union(line.bounds);}
            else if(code!=null&&league!=null&&home!=null&&line.text.startsWith("Away ")){
                bounds.union(line.bounds);result.add(new Fixture(code,home,line.text.substring(5),league,bounds));code=null;
            }
        }
        return result;
    }
    private List<Selection> markets(VisualScreen screen){
        require(screen.has("MARKETS"),"EVENT_NOT_VERIFIED","Market page not visible");
        for(String title:MARKET_NAMES.keySet())require(screen.has(title),"EVENT_NOT_VERIFIED","Market heading missing: "+title);
        List<Selection> result=new ArrayList<>();String market=null;
        Pattern quote=Pattern.compile("(HOME|AWAY|OVER|UNDER) (NONE|[+-]?[0-9]+\\.[0-9]+) ([0-9]+\\.[0-9]{2}) (OPEN|SUSPENDED|UNAVAILABLE)");
        for(VisualScreen.Line line:screen.lines){
            if(MARKET_NAMES.containsKey(line.text))market=MARKET_NAMES.get(line.text);
            else if(market!=null){Matcher m=quote.matcher(line.text);if(m.matches())result.add(new Selection(market,m.group(1),m.group(2),m.group(3),m.group(4),line.bounds));}
        }
        require(result.size()==6,"EVENT_NOT_VERIFIED","Expected six complete visible simulator quotes; found "+result.size());return result;
    }
    private Selection exactQuote(VisualScreen screen,Selection expected){
        List<Selection> matches=new ArrayList<>();for(Selection s:markets(screen))if(s.market.equals(expected.market)&&s.side.equals(expected.side))matches.add(s);
        require(matches.size()==1,"TARGET_NOT_FOUND","Quote missing or ambiguous");Selection found=matches.get(0);
        require(found.line.equals(expected.line),"LINE_CHANGED","Line changed after discovery");available(found);return found;
    }
    private void available(Selection selection){require(selection.availability.equals("OPEN"),selection.availability.equals("SUSPENDED")?"SUSPENDED":"UNAVAILABLE","Selection is "+selection.availability);}
    private static void require(boolean condition,String stage,String message){if(!condition)throw new Failure(stage,message);}
}
