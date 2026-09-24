from pathlib import Path
path = Path("android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")
old = '''    /** Casino product / Casino-only search pane — never treat as sports fixture results. */
    private static boolean isCasinoOnlyResults(VisualScreen s) {
        if (s == null) return false;
        boolean casinoUrl = false;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.toLowerCase(Locale.US);
            if (t.contains("#/ax") || t.contains("/ax/") || t.contains("#/ax/k")) { casinoUrl = true; break; }
        }
        boolean casinoChip = false;
        boolean sportsChip = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 180 || line.bounds.top > 560) continue;
            String up = line.text.trim().toUpperCase(Locale.US);
            if (up.equals("CASINO")) casinoChip = true;
            if (up.equals("SPORTS") || up.equals("FOOTBALL") || up.equals("BASKETBALL")
                    || up.equals("EVENTS") || up.equals("TEAMS") || up.equals("TENNIS")) sportsChip = true;
        }
        // Bottom-nav "Casino" alone is not enough; require Casino filter chip or Casino URL without sports rows.
        if (!(casinoChip || casinoUrl)) return false;
        if (sportsChip) return false;
        // If sports fixture rows already parse, it is not casino-only.
        // (Caller may still reject wrong sport.)
        return true;
    }'''
new = '''    /** Casino product / Casino-only search pane — never treat as sports fixture results. */
    private boolean isCasinoOnlyResults(VisualScreen s) {
        if (s == null) return false;
        // Sports fixture rows win — never classify as casino-only when v/vs pairs parse.
        if (!fixturesFromSearch(s).isEmpty()) return false;
        boolean casinoUrl = false;
        for (VisualScreen.Line line : s.lines) {
            String t = line.text.toLowerCase(Locale.US);
            if (t.contains("#/ax") || t.contains("/ax/") || t.contains("#/ax/k")) { casinoUrl = true; break; }
        }
        boolean casinoChip = false;
        boolean sportsChip = false;
        for (VisualScreen.Line line : s.lines) {
            if (line.bounds.top < 180 || line.bounds.top > 560) continue;
            String up = line.text.trim().toUpperCase(Locale.US);
            if (up.equals("CASINO")) casinoChip = true;
            if (up.equals("SPORTS") || up.equals("FOOTBALL") || up.equals("BASKETBALL")
                    || up.equals("EVENTS") || up.equals("TEAMS") || up.equals("TENNIS")) sportsChip = true;
        }
        // Require Casino filter chip or Casino URL; sports chip means not casino-only.
        if (!(casinoChip || casinoUrl)) return false;
        if (sportsChip) return false;
        return true;
    }'''
if old not in text:
    # try without special dash
    import re
    m = re.search(r'/\*\* Casino product.*?private static boolean isCasinoOnlyResults\(VisualScreen s\) \{.*?\n    \}', text, re.S)
    if not m:
        raise SystemExit('block not found')
    print('regex replace', m.start(), m.end())
    text = text[:m.start()] + new + text[m.end():]
else:
    text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
print('fixed isCasinoOnlyResults')
