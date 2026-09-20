package com.bet365agent;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;

/** Never evict IDs: a committed receipt is a permanent no-replay tombstone. */
final class CoordinatorStore extends SQLiteOpenHelper {
    CoordinatorStore(Context context) { super(context, "coordinator.db", null, 1); }
    @Override public void onConfigure(SQLiteDatabase db) { db.execSQL("PRAGMA synchronous=FULL"); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE instructions (instruction_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, received_ms INTEGER NOT NULL, received_elapsed INTEGER NOT NULL, state TEXT NOT NULL, result TEXT, execution_count INTEGER NOT NULL DEFAULT 0)");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { throw new IllegalStateException("Unsupported ledger migration"); }
    synchronized JSONObject get(String id) { return query("instruction_id=?", new String[]{id}, null); }
    synchronized JSONObject byRun(String id) { return query("run_id=?", new String[]{id}, null); }
    synchronized JSONObject active() { return query("result IS NULL", null, "received_ms DESC"); }
    synchronized JSONObject last() { return query("result IS NOT NULL", null, "rowid DESC"); }
    synchronized List<JSONObject> unfinished() {
        List<JSONObject> rows = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query("instructions", null, "result IS NULL", null, null, null, null)) {
            while (cursor.moveToNext()) rows.add(row(cursor));
        }
        return rows;
    }
    synchronized void accept(CoordinatorInstruction instruction) {
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            if (active() != null) throw new IllegalStateException("Another instruction is active");
            ContentValues values = new ContentValues();
            values.put("instruction_id", instruction.id); values.put("run_id", instruction.runId);
            values.put("payload", instruction.payload.toString()); values.put("state", "ACCEPTED");
            values.put("received_ms", System.currentTimeMillis()); values.put("received_elapsed", android.os.SystemClock.elapsedRealtime());
            db.insertOrThrow("instructions", null, values);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    synchronized void executing(String id) {
        getWritableDatabase().execSQL("UPDATE instructions SET state='EXECUTING', execution_count=execution_count+1 WHERE instruction_id=? AND state='ACCEPTED' AND result IS NULL", new Object[]{id});
    }
    synchronized void complete(String id, JSONObject result) {
        ContentValues values = new ContentValues(); values.put("state", "FINISHED"); values.put("result", result.toString());
        getWritableDatabase().update("instructions", values, "instruction_id=? AND result IS NULL", new String[]{id});
    }
    private JSONObject query(String where, String[] args, String order) {
        try (Cursor cursor = getReadableDatabase().query("instructions", null, where, args, null, null, order, "1")) {
            return cursor.moveToFirst() ? row(cursor) : null;
        }
    }
    private static JSONObject row(Cursor cursor) {
        try {
            JSONObject value = new JSONObject();
            for (String name : cursor.getColumnNames()) {
                int index = cursor.getColumnIndexOrThrow(name);
                if (cursor.isNull(index)) value.put(name, JSONObject.NULL);
                else if (cursor.getType(index) == Cursor.FIELD_TYPE_INTEGER) value.put(name, cursor.getLong(index));
                else if (name.equals("payload") || name.equals("result")) value.put(name, new JSONObject(cursor.getString(index)));
                else value.put(name, cursor.getString(index));
            }
            return value;
        } catch (Exception e) { throw new IllegalStateException("Corrupt coordinator ledger", e); }
    }
}
