package com.bet365agent;

import java.nio.file.*;
import java.util.*;
import java.util.regex.*;

/** Offline adapter for the unchanged production grid parser; no Android/device APIs. */
public final class IdentityV2Grid {
    public static void main(String[] args) throws Exception {
        List<GameLinesParser.Word> words = new ArrayList<>();
        Pattern word = Pattern.compile("^(.*?) \\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]$");
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            Matcher m = word.matcher(line);
            if (m.matches()) words.add(new GameLinesParser.Word(m.group(1),Integer.parseInt(m.group(2)),
                    Integer.parseInt(m.group(3)),Integer.parseInt(m.group(4)),Integer.parseInt(m.group(5))));
        }
        // Stored OCR serialization is not spatially ordered. The existing parser
        // uses the first header encountered; give it reading order so a later
        // half/alternative header cannot be paired with the full-game spread.
        words.sort(Comparator.comparingInt((GameLinesParser.Word w) -> w.top).thenComparingInt(w -> w.left));
        GameLinesParser.Result result = GameLinesParser.parse(words,args[1],args[2]);
        for (GameLinesParser.Cell c : result.cells)
            System.out.println(c.market+"\t"+c.side+"\t"+c.line+"\t"+c.price);
        for (String note : result.notes) System.out.println("NOTE\t"+note);
    }
}
