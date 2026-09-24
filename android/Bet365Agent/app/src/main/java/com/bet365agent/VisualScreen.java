package com.bet365agent;

import android.graphics.Rect;
import java.util.*;

/** Generic OCR geometry: group words into visually aligned lines, preserving exact text and bounds. */
final class VisualScreen {
    static final class Line {
        String text="";
        final Rect bounds=new Rect();
        final List<Integer> words=new ArrayList<>();
    }
    final List<Line> lines=new ArrayList<>();
    private final VisualControlRunner.Ocr original;
    VisualScreen(VisualControlRunner.Ocr ocr) {
        original=ocr;
        List<Integer> order=new ArrayList<>();
        for(int i=0;i<ocr.words.size();i++) if(!ocr.words.get(i).isEmpty()) order.add(i);
        order.sort(Comparator.comparingInt(i->ocr.rects.get(i).centerY()));
        for(int i:order) {
            Rect box=ocr.rects.get(i); Line chosen=null;
            for(Line line:lines) if(Math.abs(line.bounds.centerY()-box.centerY())<=Math.max(8,Math.min(line.bounds.height(),box.height())/2)) { chosen=line; break; }
            if(chosen==null) { chosen=new Line(); lines.add(chosen); }
            chosen.words.add(i); chosen.bounds.union(box);
        }
        for(Line line:lines) {
            line.words.sort(Comparator.comparingInt(i->ocr.rects.get(i).left));
            List<String> words=new ArrayList<>(); for(int i:line.words) words.add(ocr.words.get(i));
            line.text=String.join(" ",words);
        }
        lines.sort(Comparator.comparingInt(line->line.bounds.top));
    }
    Line unique(String exact) {
        List<Line> matches=new ArrayList<>(); for(Line line:lines) if(line.text.equals(exact)) matches.add(line);
        if(matches.size()!=1) throw new SiteAdapter.Failure("TARGET_NOT_FOUND","Expected one visible '"+exact+"'; found "+matches.size());
        return matches.get(0);
    }
    boolean has(String exact) { for(Line line:lines) if(line.text.equals(exact)) return true; return false; }
    /** Bounds of just the words of a phrase (case-insensitive), even when OCR merged it into a longer
     *  line such as "Home All Sports In-Play My Bets". Only lines whose top is within [minTop,maxTop]. */
    Rect phraseBounds(String phrase,int minTop,int maxTop) {
        String[] want=phrase.trim().toLowerCase(Locale.US).split("\\s+");
        for(Line line:lines) {
            if(line.bounds.top<minTop||line.bounds.top>maxTop) continue;
            for(int start=0;start+want.length<=line.words.size();start++) {
                boolean match=true;
                for(int k=0;k<want.length&&match;k++) {
                    String word=original.words.get(line.words.get(start+k)).toLowerCase(Locale.US).replaceAll("[^a-z0-9-]","");
                    match=word.equals(want[k].replaceAll("[^a-z0-9-]",""));
                }
                if(!match) continue;
                Rect r=new Rect();
                for(int k=0;k<want.length;k++) r.union(original.rects.get(line.words.get(start+k)));
                return r;
            }
        }
        return null;
    }
    Rect valueBounds(String prefix) {
        List<Line> matches=new ArrayList<>();for(Line line:lines)if(line.text.startsWith(prefix+" "))matches.add(line);
        if(matches.size()!=1)throw new SiteAdapter.Failure("EVENT_NOT_VERIFIED","Missing unique field "+prefix);
        Rect result=new Rect();Line line=matches.get(0);
        for(int n=1;n<line.words.size();n++)result.union(original.rects.get(line.words.get(n)));
        if(result.isEmpty())throw new SiteAdapter.Failure("EVENT_NOT_VERIFIED","Missing value bounds "+prefix);
        return result;
    }
    String value(String prefix) {
        List<String> values=new ArrayList<>();for(Line line:lines) if(line.text.startsWith(prefix+" ")) values.add(line.text.substring(prefix.length()+1));
        if(values.size()!=1) throw new SiteAdapter.Failure("EVENT_NOT_VERIFIED","Expected unique visible field "+prefix);
        return values.get(0);
    }
}
