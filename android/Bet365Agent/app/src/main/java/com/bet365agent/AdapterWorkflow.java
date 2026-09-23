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
    /** Per-stage soft budget; inactivity watchdog in CoordinatorAgent is the hard fail-closed. */
    private static final long STAGE_SOFT_MS = 60_000L;
    private <T> CompletableFuture<T> step(String name,Supplier<CompletableFuture<T>> action){
        if(!session.live())return VisualSession.failed("TIMEOUT","Workflow expired");
        session.checkpoint(name);
        final long stageStart = android.os.SystemClock.elapsedRealtime();
        return action.get().thenCompose(value -> {
            long took = android.os.SystemClock.elapsedRealtime() - stageStart;
            if (took > STAGE_SOFT_MS && session.live()) {
                // Soft budget exceeded but still live: record and continue; absolute/inactivity watchdogs decide.
                session.put("stage_soft_overrun_" + name, took);
            }
            return CompletableFuture.completedFuture(value);
        });
    }
    void start(String query,String market,String side,String line,String minimumPrice,String stake,String executionMode,String confirmationStatus) {
        final String mode = executionMode == null || executionMode.isEmpty() ? "ready" : executionMode;
        // Debug/harness: intentional stall after first stage advance so inactivity watchdog can be proven.
        // Not used by production OddsNotifier tips.
        if ("__STALL__".equals(query)) {
            session.checkpoint("SPORTS_HOME");
            session.put("stall_harness", true);
            session.delay(600_000L).whenComplete((v, error) -> {
                if (session.live()) session.finish("TIMEOUT", "Stall harness absolute wait ended");
            });
            return;
        }
        step("SPORTS_HOME",adapter::open_home)
        .thenCompose(v->step("SESSION_CHECK",adapter::ensure_session))
        .thenCompose(v->step("OPEN_SEARCH",adapter::open_search))
        .thenCompose(v->step("ENTER_QUERY",()->adapter.enter_query(query)))
        .thenCompose(v->step("FIXTURE_VERIFY",adapter::discover_fixture))
        .thenCompose(f->{fixture=f;session.put("fixture",f.json());return step("SELECT_FIXTURE",()->adapter.select_fixture(f));})
        .thenCompose(v->step("VERIFY_EVENT",()->adapter.verify_event(fixture)))
        .thenCompose(v->step("MARKET_NAV",adapter::discover_markets))
        .thenCompose(markets->{JSONArray json=new JSONArray();for(SiteAdapter.Selection q:markets)json.put(q.json());session.put("markets",json);return step("READ_SELECTION",()->adapter.read_selection(markets,market,side,line));})
        .thenCompose(s->{selection=s;session.put("selection",s.json());return step("READ_LINE",()->adapter.read_line(s));})
        .thenCompose(observedLine->{if(!observedLine.equals(selection.line))throw new SiteAdapter.Failure("LINE_CHANGED","Line changed while reading");return step("READ_PRICE",()->adapter.read_price(selection));})
        .thenCompose(price->{
            if(!price.equals(selection.price))throw new SiteAdapter.Failure("PRICE_CHANGED","Price changed while reading");
            if(Double.parseDouble(price)<Double.parseDouble(minimumPrice))
                throw new SiteAdapter.Failure("BELOW_MINIMUM","Visible price "+price+" is below minimum "+minimumPrice);
            return step("OPEN_SELECTION",()->adapter.open_selection(selection));
        })
        .thenCompose(v->step("ENTER_STAKE",()->adapter.enter_stake(stake)))
        .thenCompose(v->step("VERIFY_FINAL_STATE",()->adapter.verify_final_state(fixture,selection,stake)))
        .thenCompose(v->{
            if("ready".equals(mode)) return CompletableFuture.completedFuture(null);
            if(!"APPROVED".equals(confirmationStatus))
                throw new SiteAdapter.Failure("CONFIRMATION_REQUIRED","execution_mode "+mode+" requires confirmation_status APPROVED");
            session.put("confirmation_gate", confirmationStatus);
            return step("PREPARE_COMPLETE_EXECUTION",()->adapter.prepare_complete_execution(fixture,selection,stake,minimumPrice));
        })
        .thenCompose(v->{
            if(!"dispatch".equals(mode)) return CompletableFuture.completedFuture(null);
            return step("PLACE_BET",()->adapter.place_bet(fixture,selection,stake));
        })
        .whenComplete((v,error)->{
            if(error==null){
                if("dispatch".equals(mode)){
                    String detail = session.record.optString("place_bet_result", "PLACE_BET_DISPATCHED");
                    session.put("verification_detail","DISPATCH after COMPLETE_EXECUTION_READY; wager_submitted="+session.record.opt("wager_submitted"));
                    session.finish("PASS", detail);
                } else if("prepare".equals(mode)){
                    session.put("verification_detail","COMPLETE_EXECUTION_READY: Place Bet located and gesture prepared; NOT dispatched");
                    session.finish("PASS","COMPLETE_EXECUTION_READY");
                } else {
                    session.put("verification_detail","READY_STATE: session, selection, price and stake verified; stopped before wager");
                    session.finish("PASS","READY_STATE");
                }
            } else {
                Throwable cause=error;while(cause.getCause()!=null)cause=cause.getCause();
                String status=cause instanceof SiteAdapter.Failure?((SiteAdapter.Failure)cause).stage:"INTERNAL_ERROR";
                session.finish(status,cause.getMessage()==null?cause.getClass().getSimpleName():cause.getMessage());
            }
        });
    }
}
