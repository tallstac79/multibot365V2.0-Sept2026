from pathlib import Path
path = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")
old = '''    /** Positive team identity: exact or contains full multi-word query; no OCR confusion aliases. */
    private static boolean teamPositivelyIdentified(String teamName, String requested) {
        if (teamName == null || requested == null) return false;
        String t = teamName.trim().replaceAll("\\s+", " ").toLowerCase(Locale.US);
        String r = requested.trim().replaceAll("\\s+", " ").toLowerCase(Locale.US);
        if (t.isEmpty() || r.isEmpty()) return false;
        if (t.equals(r)) return true;
        if (t.contains(r)) return true;
        // Allow requested "BC Beroe" to match team "Beroe" only when requested ends with that token.
        if (r.endsWith(" " + t) && t.length() >= 4) return true;
        return false;
    }'''
new = '''    /** Strip gender/competition suffixes for identity compare (W)/(M)/Women — not search aliases. */
    private static String normalizeTeamIdentity(String raw) {
        if (raw == null) return "";
        String t = raw.trim().replaceAll("\\s+", " ");
        t = t.replaceAll("(?i)\\s*\\((?:W|M|F|Women|Men)\\)\\s*$", "");
        t = t.replaceAll("(?i)\\s+(?:Women|Men|Womens|Ladies)$", "");
        return t.trim().toLowerCase(Locale.US);
    }

    /** Positive team identity: exact or contains full multi-word query; no OCR confusion aliases. */
    private static boolean teamPositivelyIdentified(String teamName, String requested) {
        if (teamName == null || requested == null) return false;
        String t = normalizeTeamIdentity(teamName);
        String r = normalizeTeamIdentity(requested);
        if (t.isEmpty() || r.isEmpty()) return false;
        if (t.equals(r)) return true;
        if (t.contains(r)) return true;
        if (r.contains(t) && t.length() >= 4) return true;
        // Allow requested "BC Beroe" to match team "Beroe" when requested ends with that token.
        if (r.endsWith(" " + t) && t.length() >= 4) return true;
        // Allow requested "Ferrol" to match "Uni Ferrol" (team ends with requested token).
        if (t.endsWith(" " + r) && r.length() >= 4) return true;
        return false;
    }'''
if old not in text:
    raise SystemExit('teamPositivelyIdentified missing')
text = text.replace(old, new, 1)

# Also: when WRONG_EVENT on ladder but fixtures exist that identify home alias only,
# keep hard-fail for wrong opponent (correct). No change to catch list.

path.write_text(text, encoding='utf-8')
print('identity normalize patched')
