package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Read-only bounded history; delivery ACKs, tasks and control are never changed. */
final class JournalHistory {
    static final int CHUNK_BYTES = 24 * 1024, PAGE_BYTES = 48 * 1024;
    private JournalHistory() {}

    static JsonObject page(Connection db, JsonObject params) throws SQLException {
        String source = str(params, "source");
        Map<String,String> tables = Map.of("reliable", "reliable", "task_versions", "task_transitions",
            "retention_summaries", "journal_summaries", "retired_tasks", "journal_retired_tasks", "retention_runs", "journal_retention_runs");
        require(tables.containsKey(source), "GAME_HISTORY_SOURCE");
        String table = tables.get(source);
        long after = num(params, "after"); int offset = Math.toIntExact(num(params, "offset")), limit = Math.toIntExact(num(params, "limit"));
        require(after >= 0 && offset >= 0 && offset < Wire.MAX_BYTES && limit >= 1 && limit <= 20, "GAME_HISTORY_CURSOR");
        long maximum;
        try (Statement query = db.createStatement(); ResultSet rows = query.executeQuery("SELECT coalesce(max(rowid),0) FROM " + table)) {
            require(rows.next(), "GAME_HISTORY_WINDOW_CHANGED"); maximum = rows.getLong(1);
        }
        long through = params.get("through").isJsonNull() ? maximum : num(params, "through");
        require(through >= after && through <= maximum && (after < through || offset == 0), "GAME_HISTORY_WINDOW_CHANGED");
        String columns = switch(source) {
            case "reliable" -> "rowid,boot,world,stream,delivery_seq,type,payload,created_at,acked_at,archived_at,archive_reason";
            case "task_versions" -> "rowid,task_id,version,task,recorded_at";
            case "retention_summaries" -> "rowid,summary_key,value";
            case "retired_tasks" -> "rowid,task_id,world,request_id,body_hash,retired_at,summary";
            default -> "rowid,run_id,result";
        };
        JsonArray chunks = new JsonArray(); long nextAfter = after; int nextOffset = offset, budget = PAGE_BYTES;
        try (PreparedStatement query = db.prepareStatement("SELECT " + columns + " FROM " + table + " WHERE rowid>? AND rowid<=? ORDER BY rowid LIMIT ?")) {
            query.setLong(1, after); query.setLong(2, through); query.setInt(3, limit);
            try (ResultSet rows = query.executeQuery()) {
                while (rows.next() && budget > 0) {
                    long row = rows.getLong(1);
                    JsonObject maintenance = Set.of("retention_summaries", "retired_tasks", "retention_runs").contains(source)
                        ? maintenancePayload(db, source, rows) : null;
                    String raw = maintenance == null ? rows.getString(source.equals("reliable") ? 7 : 4) : canonical(maintenance);
                    byte[] bytes = raw.getBytes(StandardCharsets.UTF_8);
                    require(bytes.length > 0 && bytes.length <= Wire.MAX_BYTES && nextOffset < bytes.length, "GAME_HISTORY_ROW_SIZE_OR_OFFSET");
                    JsonObject chunk;
                    if (source.equals("reliable")) {
                        JsonArray key = GSON.toJsonTree(List.of(rows.getString(2), rows.getString(3), rows.getString(4), rows.getLong(5))).getAsJsonArray();
                        chunk = obj("record_key", hash(canonical(key)), "source_id", row, "source_boot_id", rows.getString(2),
                            "world_session_id", rows.getString(3), "stream", rows.getString(4), "sequence", rows.getLong(5), "type", rows.getString(6),
                            "recorded_at", rows.getLong(8), "acked_at", rows.getObject(9), "archived_at", rows.getObject(10), "archive_reason", rows.getString(11));
                    } else if (source.equals("task_versions")) {
                        JsonObject task = JsonParser.parseString(raw).getAsJsonObject();
                        JsonArray key = GSON.toJsonTree(List.of(rows.getString(2), rows.getLong(3))).getAsJsonArray();
                        chunk = obj("record_key", hash(canonical(key)), "source_id", row, "source_boot_id", task.get("bridge_boot_id"),
                            "world_session_id", task.get("world_session_id"), "stream", "task_versions", "sequence", rows.getLong(3), "type", "task_version",
                            "recorded_at", rows.getLong(5), "acked_at", null, "archived_at", null, "archive_reason", null);
                    } else {
                        JsonObject value = maintenance.getAsJsonObject("value");
                        JsonObject summary = source.equals("retired_tasks") ? value.getAsJsonObject("summary") : null;
                        Object boot = summary == null ? null : summary.get("bridge_boot_id");
                        Object world = source.equals("retention_summaries") ? value.get("world_session_id") : summary == null ? null : summary.get("world_session_id");
                        long recorded = source.equals("retention_summaries") ? num(value, "last_recorded_at")
                            : source.equals("retired_tasks") ? num(value, "retired_at") : Instant.parse(str(value, "completed_at")).toEpochMilli();
                        JsonArray key = GSON.toJsonTree(List.of(source, str(maintenance, "source_key"), hash(raw))).getAsJsonArray();
                        chunk = obj("record_key", hash(canonical(key)), "source_id", row, "source_boot_id", boot,
                            "world_session_id", world, "stream", source, "sequence", 0,
                            "type", source.equals("retention_summaries") ? "retention_summary" : source.equals("retired_tasks") ? "retired_task" : "retention_run",
                            "recorded_at", recorded, "acked_at", null, "archived_at", null, "archive_reason", null);
                    }
                    int length = Math.min(Math.min(CHUNK_BYTES, budget), bytes.length - nextOffset);
                    boolean last = nextOffset + length == bytes.length;
                    chunk.addProperty("payload_sha256", hash(raw)); chunk.addProperty("payload_bytes", bytes.length);
                    chunk.addProperty("offset", nextOffset); chunk.addProperty("data_base64", Base64.getEncoder().encodeToString(Arrays.copyOfRange(bytes, nextOffset, nextOffset + length)));
                    chunk.addProperty("final", last); chunks.add(chunk); budget -= length;
                    if (!last) { nextOffset += length; break; }
                    nextAfter = row; nextOffset = 0;
                }
            }
        }
        require(offset == 0 || !chunks.isEmpty(), "GAME_HISTORY_WINDOW_CHANGED");
        boolean complete = false;
        if (nextOffset == 0) {
            try (PreparedStatement query = db.prepareStatement("SELECT 1 FROM " + table + " WHERE rowid>? AND rowid<=? LIMIT 1")) {
                query.setLong(1, nextAfter); query.setLong(2, through);
                try (ResultSet rows = query.executeQuery()) { complete = !rows.next(); }
            }
        }
        return obj("source", source, "after", after, "offset", offset, "through", through,
            "next_after", nextAfter, "next_offset", nextOffset, "complete", complete, "chunks", chunks);
    }
    private static JsonObject maintenancePayload(Connection db, String source, ResultSet row) throws SQLException {
        String instance;
        try (Statement query = db.createStatement(); ResultSet result = query.executeQuery("SELECT value FROM metadata WHERE key='instance_id'")) {
            require(result.next(), "GAME_JOURNAL_INSTANCE"); instance = result.getString(1);
        }
        JsonObject value = source.equals("retired_tasks")
            ? obj("world_session_id", row.getString(3), "request_id", row.getString(4), "task_id", row.getString(2),
                "body_hash", row.getString(5), "retired_at", row.getLong(6), "summary", JsonParser.parseString(row.getString(7)))
            : JsonParser.parseString(row.getString(3)).getAsJsonObject();
        return obj("game_instance_id", instance, "source", source, "source_key", row.getString(2), "value", value);
    }
}
