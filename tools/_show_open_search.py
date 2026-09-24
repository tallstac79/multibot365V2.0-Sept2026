from pathlib import Path
path = Path(r"android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java")
text = path.read_text(encoding="utf-8")
start = text.find("    public CompletableFuture<Void> open_search()")
end = text.find("    public CompletableFuture<Void> enter_query(")
print("start", start, "end", end)
print(repr(text[start:end][:500]))
print("---FULL BLOCK---")
print(text[start:end])
