from pathlib import Path
import re

# Java: fail-fast WRONG_EVENT when home matches but required away does not,
# and do not spend ladder budget retyping after home-only miss with expectedAway.
path = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")

# In runSearchQueryLadder catch block — keep AMBIGUOUS/WRONG throw.
# Also: when fixtures non-empty but assert fails with WRONG_EVENT, already throws.

# Sanitize slash in typed queries (Kalev/Cramo)
old_type = "private CompletableFuture<VisualScreen> typeSearchQueryOnce(String queryText) {"
new_type = '''private static String sanitizeSearchTyped(String q) {
        if (q == null) return "";
        // Bet365 search rejects or OCR-breaks on slash-heavy club names; discovery only.
        return q.replace('/', ' ').replaceAll("\\\\s+", " ").trim();
    }

    private CompletableFuture<VisualScreen> typeSearchQueryOnce(String queryText) {
        queryText = sanitizeSearchTyped(queryText);'''
if old_type not in text:
    raise SystemExit('typeSearchQueryOnce missing')
text = text.replace(old_type, new_type, 1)

# When expectedAway set, after finding sports fixtures that identify home but not away,
# selectUniqueFixture already throws WRONG_EVENT. Ensure ladder does not treat empty
# casino recover loops: if casino-only after recover flag, advance index (already does).

# Faster wrong-opponent: put single-home query earlier when away looks non-team (long/no space rare tokens)
old_ladder_build = '''        // A/D first when prefix alias exists: "Beroe Ferrol", then full "BC Beroe Ferrol"
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
        for (String aa : awayAliases) out.add(aa);'''

new_ladder_build = '''        boolean awayLooksReal = a.length() >= 3 && a.length() <= 28 && a.matches("(?i)[A-Za-z0-9 .'-]+");
        // A/D first when prefix alias exists: "Beroe Ferrol", then full "BC Beroe Ferrol"
        if (!h.isEmpty() && !a.isEmpty() && awayLooksReal) {
            for (String ha : homeAliases) out.add(ha + " " + a);
            for (String ha : homeAliases) {
                for (String aa : awayAliases) out.add(ha + " " + aa);
            }
            out.add(h + " " + a);
        }
        // D single-team aliases before raw prefixed home (Casino magnet)
        for (String ha : homeAliases) out.add(ha);
        if (!h.isEmpty()) out.add(h);
        // Non-real away: still try once so wrong-opponent fails closed via identity gate on home hits
        if (!a.isEmpty() && awayLooksReal) out.add(a);
        for (String aa : awayAliases) out.add(aa);
        if (!h.isEmpty() && !a.isEmpty() && !awayLooksReal) {
            // Keep one combined attempt last (bounded); identity still requires both teams.
            out.add(h + " " + a);
        }'''

if old_ladder_build not in text:
    raise SystemExit('ladder build block missing')
text = text.replace(old_ladder_build, new_ladder_build, 1)

path.write_text(text, encoding="utf-8")
print("java patched")
