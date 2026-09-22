package com.bet365agent;

import java.util.concurrent.CompletableFuture;
import java.util.function.Supplier;
import org.json.JSONArray;

/** Generic state machine: no site names, DOM selectors, screen labels or layout assumptions. */
final class AdapterWorkflow {
    private final VisualSession session;
    private final SiteAdapter adapter;
    private SiteAdapter.Fixture fixture;
    private SiteAdapter.Selection selection;
    AdapterWorkflow(VisualSession session,SiteAdapter adapter){this.session=session;this.adapter=adapter;}
    private <T> CompletableFuture<T> step(String name,Supplier<CompletableFuture<T>> action){
        if(!session.live())return VisualSession.failed("TIMEOUT","Workflow expired");
        session.checkpoint(name);return action.get();
    }
    void start(String query,String market,String side,String minimumPrice,String stake) {
        step("OPEN_HOME",adapter::open_home)
        .thenCompose(v->step("OPEN_SEARCH",adapter::open_search))
        .thenCompose(v->step("ENTER_QUERY",()->adapter.enter_query(query)))
        .thenCompose(v->step("DISCOVER_FIXTURE",adapter::discover_fixture))
        .thenCompose(f->{fixture=f;session.put("fixture",f.json());return step("SELECT_FIXTURE",()->adapter.select_fixture(f));})
        .thenCompose(v->step("VERIFY_EVENT",()->adapter.verify_event(fixture)))
        .thenCompose(v->step("DISCOVER_MARKETS",adapter::discover_markets))
        .thenCompose(markets->{JSONArray json=new JSONArray();for(SiteAdapter.Selection q:markets)json.put(q.json());session.put("markets",json);return step("READ_SELECTION",()->adapter.read_selection(markets,market,side));})
        .thenCompose(s->{selection=s;session.put("selection",s.json());return step("READ_LINE",()->adapter.read_line(s));})
        .thenCompose(line->{if(!line.equals(selection.line))throw new SiteAdapter.Failure("LINE_CHANGED","Line changed while reading");return step("READ_PRICE",()->adapter.read_price(selection));})
        .thenCompose(price->{
            if(!price.equals(selection.price))throw new SiteAdapter.Failure("PRICE_CHANGED","Price changed while reading");
            if(Double.parseDouble(price)<Double.parseDouble(minimumPrice))
                throw new SiteAdapter.Failure("BELOW_MINIMUM","Visible price "+price+" is below minimum "+minimumPrice);
            return step("OPEN_SELECTION",()->adapter.open_selection(selection));
        })
        .thenCompose(v->step("VERIFY_FINAL_STATE",()->adapter.verify_final_state(fixture,selection,stake)))
        .whenComplete((v,error)->{
            if(error==null){session.put("verification_detail","Exact fixture, market, side, line and price visually verified in final dry-run state");session.finish("PASS","Adapter workflow verified");}
            else {Throwable cause=error;while(cause.getCause()!=null)cause=cause.getCause();String status=cause instanceof SiteAdapter.Failure?((SiteAdapter.Failure)cause).stage:"INTERNAL_ERROR";session.finish(status,cause.getMessage()==null?cause.getClass().getSimpleName():cause.getMessage());}
        });
    }
}
