package com.bet365agent;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The desktop worker's decision bridge: the PHONE'S OWN pure-Java decisions (event identity, competition structure,
 * kick-off, football line band, line/price tolerances, slip names), compiled unchanged from the Android sources and
 * driven over stdin/stdout by desktop_worker/decisions.py. Nothing here decides anything itself; it only marshals.
 *
 * Protocol: one request per line, fields separated by TAB; a list field joins items with U+001F; a map field joins
 * entries with U+001F and key/value with U+001E. One JSON object per response line: {"ok":true,"value":...} or
 * {"ok":false,"error":"..."}.
 */
public final class DesktopDecisions {
    private static final String LIST = "\u001f", KV = "\u001e";

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        PrintStream out = new PrintStream(System.out, true, "UTF-8");
        for (String line; (line = in.readLine()) != null; ) {
            if (line.isEmpty()) continue;
            Map<String, Object> reply = new LinkedHashMap<>();
            try {
                reply.put("value", handle(line.split("\t", -1)));
                reply.put("ok", true);
            } catch (Throwable t) {
                reply.put("ok", false);
                reply.put("error", t.getClass().getSimpleName() + ": " + t.getMessage());
            }
            out.println(json(reply));
        }
    }

    static List<String> list(String s) { return s.isEmpty() ? new ArrayList<>() : new ArrayList<>(Arrays.asList(s.split(LIST, -1))); }

    static Map<String, String> map(String s) {
        Map<String, String> m = new LinkedHashMap<>();
        for (String e : list(s)) { String[] kv = e.split(KV, 2); if (kv.length == 2) m.put(EventIdentity.plain(kv[0]), kv[1]); }
        return m;
    }

    static List<String[]> quotes(String s) {
        List<String[]> out = new ArrayList<>();
        for (String q : list(s)) { String[] f = q.split(KV, -1); out.add(FootballLineCheck.quote(f[0], f[1], f[2], f[3])); }
        return out;
    }

    static Object handle(String[] a) {
        switch (a[0]) {
            case "ping": return "pong";
            case "uk": return EventPage.ukDisplay(a[1]);
            case "teams": { String[] t = EventPage.teams(list(a[1])); return t == null ? null : Arrays.asList(t); }
            case "decide": return decide(a);
            case "competition_key": return EventIdentity.competitionKey(a[1]);
            case "nearest": return FootballLineCheck.nearest(quotes(a[1]), a[2], a[3], a[4], a[5]);
            case "refusal": return FootballLineCheck.lineRefusal(quotes(a[1]), a[2], a[3], a[4], a[5]);
            case "fresh": { String[] r = FootballLineCheck.freshTerms(a[1], a[2], a[3], a[4], a[5], a[6], a[7]); return r == null ? null : Arrays.asList(r); }
            case "line": return ExecutionTolerance.lineForSport(a[1], a[2], a[3], a[4], a[5], a[6]);
            case "price": return ExecutionTolerance.price(a[1], a[2]);
            case "same_slip_name": return HeldSlipIdentity.sameSlipName(a[1], a[2]);
            case "norm_line": return FootballMarkets.normaliseLine(a[1]);
            default: throw new IllegalArgumentException("unknown op " + a[0]);
        }
    }

    /** decide TAB header TAB sport TAB feedHome TAB feedAway TAB kickoffUtc TAB competition TAB country TAB anchored TAB women TAB aliases */
    static Object decide(String[] a) {
        List<String> header = list(a[1]);
        String want = a[5].isEmpty() ? null : EventPage.ukDisplay(a[5]);
        EventPage.Direct d = EventPage.decide(header, a[2], a[3], a[4], want, a[6], a[7], "1".equals(a[8]), map(a[10]), "1".equals(a[9]));
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("header", header);
        m.put("teams", d.teams == null ? null : Arrays.asList(d.teams));
        m.put("kickoff_shown", d.shown);
        m.put("kickoff_expected", want);
        String page = header.isEmpty() ? null : header.get(0);
        m.put("competition_key", page == null ? null : EventIdentity.competitionKey(page));
        m.put("competition_matches", EventIdentity.competitionMatches(a[6], a[7], page));
        EventIdentity.Result r = d.result;
        if (r == null) return m;
        m.put("verdict", r.verdict.name());
        m.put("accepted", r.accepted());
        m.put("reason", r.reason);
        m.put("home", side(r.home));
        m.put("away", side(r.away));
        m.put("kickoff_known", r.kickoffKnown);
        m.put("kickoff_agrees", r.kickoffAgrees);
        m.put("reversed", r.reversed);
        m.put("alias_candidates", r.aliasCandidates);
        m.put("confidence", r.candidateConfidence);
        m.put("evidence", r.evidence);
        return m;
    }

    static Map<String, Object> side(EventIdentity.Side s) {
        if (s == null) return null;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("feed", s.feed); m.put("bookmaker", s.bookmaker); m.put("level", s.level.name()); m.put("kind", s.kind);
        m.put("score", Math.round(s.score * 100) / 100.0); m.put("note", s.note); m.put("alias_safe", s.aliasSafe);
        if (s.recheck != null) m.put("recheck", s.recheck);
        return m;
    }

    static String json(Object o) {
        if (o == null) return "null";
        if (o instanceof Boolean || o instanceof Integer || o instanceof Long) return o.toString();
        if (o instanceof Double || o instanceof Float) { double v = ((Number) o).doubleValue(); return Double.isFinite(v) ? String.valueOf(v) : "null"; }
        if (o instanceof Number) return o.toString();
        if (o instanceof Map) {
            StringBuilder sb = new StringBuilder("{"); boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) o).entrySet()) {
                if (!first) sb.append(','); first = false;
                sb.append(json(String.valueOf(e.getKey()))).append(':').append(json(e.getValue()));
            }
            return sb.append('}').toString();
        }
        if (o instanceof Collection) {
            StringBuilder sb = new StringBuilder("["); boolean first = true;
            for (Object e : (Collection<?>) o) { if (!first) sb.append(','); first = false; sb.append(json(e)); }
            return sb.append(']').toString();
        }
        if (o instanceof Object[]) return json(Arrays.asList((Object[]) o));
        String s = o.toString();
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') sb.append('\\').append(c);
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.append('"').toString();
    }
}
