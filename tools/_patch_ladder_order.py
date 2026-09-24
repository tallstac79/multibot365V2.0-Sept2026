from pathlib import Path
path = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")
old = '''    private static List<String> buildSearchQueryLadder(String home, String away) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        String h = home == null ? "" : home.trim();
        String a = away == null ? "" : away.trim();
        if (!h.isEmpty() && !a.isEmpty()) out.add(h + " " + a);
        if (!h.isEmpty()) out.add(h);
        if (!a.isEmpty()) out.add(a);
        for (String alias : searchAliasesFor(h)) out.add(alias);
        if (!a.isEmpty()) {
            for (String alias : searchAliasesFor(a)) out.add(alias);
            // Alias home + full away, and alias-home + alias-away
            for (String ha : searchAliasesFor(h)) {
                out.add(ha + " " + a);
                for (String aa : searchAliasesFor(a)) out.add(ha + " " + aa);
            }
        }
        out.removeIf(s -> s == null || s.trim().isEmpty());
        return new ArrayList<>(out);
    }'''
new = '''    private static List<String> buildSearchQueryLadder(String home, String away) {
        // Prefer alias forms early: "BC …" queries often resolve Casino-only on Bet365.
        LinkedHashSet<String> out = new LinkedHashSet<>();
        String h = home == null ? "" : home.trim();
        String a = away == null ? "" : away.trim();
        List<String> homeAliases = searchAliasesFor(h);
        List<String> awayAliases = searchAliasesFor(a);
        // A/D first when prefix alias exists: "Beroe Ferrol", then full "BC Beroe Ferrol"
        if (!h.isEmpty() && !a.isEmpty()) {
            for (String ha : homeAliases) out.add(ha + " " + a);
            for (String ha : homeAliases) {
                for (String aa : awayAliases) out.add(ha + " " + aa);
            }
            out.add(h + " " + a);
        }
        // D single-team aliases before raw prefixed home (Casino magnet)
        for (String ha : homeAliases) out.add(ha);
        if (!h.isEmpty()) out.add(h);
        if (!a.isEmpty()) out.add(a);
        for (String aa : awayAliases) out.add(aa);
        out.removeIf(s -> s == null || s.trim().isEmpty());
        // Bound ladder length for 120s instruction budget
        ArrayList<String> list = new ArrayList<>(out);
        if (list.size() > 6) return new ArrayList<>(list.subList(0, 6));
        return list;
    }'''
if old not in text:
    raise SystemExit('ladder block missing')
text = text.replace(old, new, 1)
# slightly faster post-type wait
text = text.replace(
    '.thenCompose(v -> ui.delay(1200)).thenCompose(v -> ui.capture("query_results"));',
    '.thenCompose(v -> ui.delay(900)).thenCompose(v -> ui.capture("query_results"));',
    1)
path.write_text(text, encoding='utf-8')
print('ladder reordered')
