package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.sqlite.SQLiteConfig;
import org.sqlite.SQLiteConnection;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** One off-game-thread writer. Task, transition and delivery commit before effects. */
public final class LocalJournal implements AutoCloseable {
    public static final int SCHEMA_VERSION = 3;
    public static final int TASK_LIMIT = 20_000, RELIABLE_LIMIT = 50_000;
    private final Path directory;
    private final Ownership ownership;
    private final Connection db;
    private final String instance;
    private final boolean maintenanceOnly;
    private boolean closed;
    private final java.util.concurrent.atomic.AtomicLong transactionCount = new java.util.concurrent.atomic.AtomicLong();
    private final java.util.concurrent.atomic.AtomicLong lastTransactionNanos = new java.util.concurrent.atomic.AtomicLong();
    private final java.util.concurrent.atomic.AtomicLong maxTransactionNanos = new java.util.concurrent.atomic.AtomicLong();

    public LocalJournal(Path directory) throws IOException {
        this(directory, false);
    }
    /** Exclusive offline maintenance never converts unfinished tasks into restart failures. */
    public static LocalJournal openForMaintenance(Path directory) throws IOException {
        Path root = directory.toAbsolutePath().normalize();
        require(Files.isRegularFile(root.resolve("mc-control.sqlite3")) && !Files.isSymbolicLink(root.resolve("mc-control.sqlite3")), "GAME_JOURNAL_MISSING");
        return new LocalJournal(root, true);
    }
    private LocalJournal(Path directory, boolean maintenanceOnly) throws IOException {
        this.maintenanceOnly = maintenanceOnly;
        this.directory = directory.toAbsolutePath().normalize();
        Files.createDirectories(this.directory); ownership = new Ownership(this.directory);
        Connection connection = null;
        try {
            prepareNative(this.directory);
            Path file = this.directory.resolve("mc-control.sqlite3");
            connection = connect(file, false); db = connection;
            int version = (int) scalar("PRAGMA user_version");
            require(!maintenanceOnly || version != 0, "GAME_JOURNAL_UNVERSIONED");
            require(version == 0 || version == 2 || version == SCHEMA_VERSION, "GAME_JOURNAL_VERSION");
            if (version == 0) require(scalar("SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'") == 0, "GAME_JOURNAL_UNVERSIONED");
            execute("PRAGMA busy_timeout=2000"); execute("PRAGMA foreign_keys=ON");
            require("wal".equalsIgnoreCase(text("PRAGMA journal_mode=WAL")), "GAME_JOURNAL_WAL_UNAVAILABLE");
            execute("PRAGMA synchronous=FULL"); execute("PRAGMA wal_autocheckpoint=1000");
            // Bound the database itself; journal rows have an additional admission budget.
            execute("PRAGMA max_page_count=65536");
            if (version == 0) initialize();
            else if (version == 2) {
                backup(db, this.directory, "schema-v2");
                transaction(() -> { retentionSchema(); execute("PRAGMA user_version=3"); return null; });
            }
            require("ok".equals(text("PRAGMA quick_check")), "GAME_JOURNAL_INTEGRITY");
            instance = text("SELECT value FROM metadata WHERE key='instance_id'");
            require(instance != null && instance.startsWith("mc-"), "GAME_JOURNAL_INSTANCE");
            if (!maintenanceOnly) recoverUnfinished();
        } catch (Throwable error) {
            if (connection != null) try { connection.close(); } catch (SQLException cleanup) { error.addSuppressed(cleanup); }
            try { ownership.close(); } catch (IOException cleanup) { error.addSuppressed(cleanup); }
            if (error instanceof SQLException sql) throw io(sql);
            if (error instanceof IOException failure) throw failure;
            if (error instanceof RuntimeException runtime) throw runtime;
            throw new IOException("GAME_JOURNAL_OPEN_FAILED", error);
        }
    }

    private static void prepareNative(Path directory) throws IOException, ClassNotFoundException {
        // SQLite JDBC loads once per JVM. Never extract native code to an unowned temp root.
        synchronized (LocalJournal.class) {
            if (System.getProperty("org.sqlite.tmpdir") == null) {
                Path nativeDir = directory.resolve("native"); Files.createDirectories(nativeDir);
                System.setProperty("org.sqlite.tmpdir", nativeDir.toString());
            }
            Class.forName("org.sqlite.JDBC");
        }
    }
    private static Connection connect(Path file, boolean readOnly) throws SQLException {
        SQLiteConfig settings = new SQLiteConfig(); settings.setReadOnly(readOnly); settings.setBusyTimeout(2000);
        return DriverManager.getConnection("jdbc:sqlite:" + file, settings.toProperties());
    }
    private static IOException io(SQLException error) { return new IOException("GAME_LOCAL_SQLITE_ERROR", error); }
    private PreparedStatement statement(String sql, Object... args) throws SQLException {
        PreparedStatement result = db.prepareStatement(sql);
        try { for (int i = 0; i < args.length; i++) result.setObject(i + 1, args[i]); return result; }
        catch (SQLException error) { result.close(); throw error; }
    }
    private int execute(String sql, Object... args) throws SQLException {
        try (PreparedStatement query = statement(sql, args)) { query.execute(); return query.getUpdateCount(); }
    }
    private long scalar(String sql, Object... args) throws SQLException {
        try (PreparedStatement query = statement(sql, args); ResultSet rows = query.executeQuery()) { return rows.next() ? rows.getLong(1) : 0; }
    }
    private String text(String sql, Object... args) throws SQLException {
        try (PreparedStatement query = statement(sql, args); ResultSet rows = query.executeQuery()) { return rows.next() ? rows.getString(1) : null; }
    }
    @FunctionalInterface private interface Work<T> { T run() throws SQLException, IOException; }
    private <T> T transaction(Work<T> work) throws IOException {
        long began = System.nanoTime();
        try {
            db.setAutoCommit(false);
            try { T result = work.run(); db.commit(); return result; }
            catch (Throwable error) { try { db.rollback(); } catch (SQLException cleanup) { error.addSuppressed(cleanup); } throw error; }
            finally { db.setAutoCommit(true); }
        } catch (SQLException error) { throw io(error); }
        finally {
            long elapsed = Math.max(0, System.nanoTime() - began);
            lastTransactionNanos.set(elapsed); maxTransactionNanos.accumulateAndGet(elapsed, Math::max); transactionCount.incrementAndGet();
        }
    }
    /** Does not acquire the DB monitor, query SQLite, expose paths or perform I/O. */
    public JsonObject timings() { return obj("transactions", transactionCount.get(), "last_transaction_ms", lastTransactionNanos.get() / 1_000_000.0,
            "max_transaction_ms", maxTransactionNanos.get() / 1_000_000.0); }
    private static JsonObject parse(String json) { return JsonParser.parseString(json).getAsJsonObject(); }
    private static String json(JsonElement value) {
        String result = GSON.toJson(value);
        require(result.getBytes(StandardCharsets.UTF_8).length <= Wire.MAX_BYTES, "GAME_JOURNAL_ROW_TOO_LARGE");
        return result;
    }
    private static String stream(String type) {
        require(Set.of("task_update", "game_event").contains(type), "GAME_LOCAL_STREAM_INVALID");
        return type.equals("task_update") ? "task_transitions" : "events";
    }

    private void initialize() throws IOException {
        Path legacy = directory.resolve("journal.json"); JsonObject imported = null;
        if (Files.exists(legacy)) {
            require(Files.size(legacy) <= 8 * 1024 * 1024, "GAME_JOURNAL_TOO_LARGE");
            imported = parse(Files.readString(legacy, StandardCharsets.UTF_8));
            require(num(imported, "schema_version") == 1, "GAME_JOURNAL_VERSION");
            String digest = digest(legacy); Path backups = directory.resolve("backups"); Files.createDirectories(backups);
            Path copy = backups.resolve("legacy-v1-" + digest + ".json");
            if (!Files.exists(copy)) copyDurably(legacy, copy);
            require(digest.equals(digest(copy)), "GAME_JOURNAL_BACKUP_MISMATCH");
        }
        JsonObject source = imported;
        transaction(() -> {
            execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)");
            execute("CREATE TABLE worlds(key_hash TEXT PRIMARY KEY, world_id TEXT NOT NULL UNIQUE)");
            execute("CREATE TABLE tasks(world TEXT NOT NULL, request_id TEXT NOT NULL, body_hash TEXT NOT NULL, task_id TEXT NOT NULL UNIQUE, version INTEGER NOT NULL CHECK(version>0), state TEXT NOT NULL, task TEXT NOT NULL CHECK(json_valid(task)), PRIMARY KEY(world,request_id))");
            execute("CREATE TABLE task_transitions(task_id TEXT NOT NULL REFERENCES tasks(task_id), version INTEGER NOT NULL, task TEXT NOT NULL CHECK(json_valid(task)), recorded_at INTEGER NOT NULL, PRIMARY KEY(task_id,version))");
            execute("CREATE TABLE contexts(boot TEXT NOT NULL, world TEXT NOT NULL, opened_at INTEGER NOT NULL, closed_at INTEGER, reason TEXT, PRIMARY KEY(boot,world))");
            execute("CREATE TABLE streams(boot TEXT NOT NULL, world TEXT NOT NULL, stream TEXT NOT NULL, issued INTEGER NOT NULL CHECK(issued>=0), acked INTEGER NOT NULL DEFAULT 0 CHECK(acked>=0 AND acked<=issued), PRIMARY KEY(boot,world,stream))");
            execute("CREATE TABLE reliable(boot TEXT NOT NULL, world TEXT NOT NULL, stream TEXT NOT NULL, delivery_seq INTEGER NOT NULL CHECK(delivery_seq>0), type TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)), created_at INTEGER NOT NULL, archived_at INTEGER, archive_reason TEXT, acked_at INTEGER, PRIMARY KEY(boot,world,stream,delivery_seq), FOREIGN KEY(boot,world,stream) REFERENCES streams(boot,world,stream))");
            execute("CREATE INDEX reliable_pending ON reliable(boot,world,acked_at,archived_at,stream,delivery_seq)");
            execute("INSERT INTO metadata VALUES('instance_id',?)", source == null ? "mc-" + UUID.randomUUID() : str(source, "instance_id"));
            execute("INSERT INTO metadata VALUES('active_boot',''),('active_world','')");
            retentionSchema();
            if (source != null) importLegacy(source);
            execute("PRAGMA user_version=3"); return null;
        });
    }
    private void retentionSchema() throws SQLException {
        JournalRetention.createSchema(db);
    }
    private long nextHistoryId(String table, String key) throws SQLException {
        long previous = Math.max(scalar("SELECT coalesce(max(rowid),0) FROM " + table), Long.parseLong(text("SELECT value FROM metadata WHERE key=?", key)));
        long next = Math.addExact(previous, 1);
        execute("UPDATE metadata SET value=? WHERE key=?", Long.toString(next), key); return next;
    }
    private void importLegacy(JsonObject source) throws SQLException {
        require(source.getAsJsonObject("tasks").size() <= TASK_LIMIT && source.getAsJsonArray("outbox").size() <= 256, "GAME_JOURNAL_LEGACY_LIMIT");
        for (var entry : source.getAsJsonObject("worlds").entrySet()) execute("INSERT INTO worlds VALUES(?,?)", entry.getKey(), entry.getValue().getAsString());
        for (var entry : source.getAsJsonObject("tasks").entrySet()) {
            JsonObject record = entry.getValue().getAsJsonObject(), task = record.getAsJsonObject("task");
            String world = str(task, "world_session_id"), request = str(task, "request_id");
            require(entry.getKey().equals(world + ":" + request), "GAME_JOURNAL_LEGACY_CONTEXT");
            require(str(record, "hash").matches("[0-9a-f]{64}"), "GAME_JOURNAL_LEGACY_HASH");
            insertTask(world, request, str(record, "hash"), task);
        }
        for (var entry : source.getAsJsonObject("counters").entrySet()) {
            String[] key = entry.getKey().split(":", -1); require(key.length == 3, "GAME_JOURNAL_LEGACY_COUNTER");
            require(Set.of("events", "task_transitions").contains(key[2]), "GAME_JOURNAL_LEGACY_COUNTER");
            execute("INSERT INTO streams(boot,world,stream,issued) VALUES(?,?,?,?)", key[0], key[1], key[2], entry.getValue().getAsLong());
        }
        for (JsonElement value : source.getAsJsonArray("outbox")) {
            JsonObject row = value.getAsJsonObject(), payload = row.getAsJsonObject("payload");
            String boot = str(row, "boot"), world = str(row, "world"), stream = str(row, "stream"); long seq = num(payload, "delivery_seq");
            require(stream.equals(stream(str(row, "type"))) && seq > 0 && seq <= scalar("SELECT issued FROM streams WHERE boot=? AND world=? AND stream=?", boot, world, stream), "GAME_JOURNAL_LEGACY_COUNTER");
            execute("INSERT INTO reliable(boot,world,stream,delivery_seq,type,payload,created_at) VALUES(?,?,?,?,?,?,?)", boot, world, stream, seq, str(row, "type"), json(payload), System.currentTimeMillis());
        }
        execute("INSERT INTO metadata VALUES('legacy_imported','1')");
    }
    private void insertTask(String world, String request, String hash, JsonObject task) throws SQLException {
        require(world.equals(str(task, "world_session_id")) && request.equals(str(task, "request_id")), "GAME_LOCAL_TASK_CONTEXT");
        execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", world, request, hash, str(task, "task_id"), num(task, "version"), str(task, "state"), json(task));
        transition(task);
    }
    private void transition(JsonObject task) throws SQLException {
        execute("INSERT INTO task_transitions(rowid,task_id,version,task,recorded_at) VALUES(?,?,?,?,?)", nextHistoryId("task_transitions", "history_tasks_highwater"),
                str(task, "task_id"), num(task, "version"), json(task), System.currentTimeMillis());
    }
    private void recoverUnfinished() throws IOException {
        transaction(() -> {
            List<JsonObject> interrupted = new ArrayList<>();
            try (PreparedStatement query = statement("SELECT task FROM tasks WHERE state IN ('accepted','running')"); ResultSet rows = query.executeQuery()) {
                while (rows.next()) interrupted.add(parse(rows.getString(1)));
            }
            for (JsonObject task : interrupted) {
                task.addProperty("state", "failed"); task.addProperty("reason", "INTERRUPTED_RESTART"); task.addProperty("effect_status", "unknown");
                task.addProperty("version", num(task, "version") + 1); task.addProperty("updated_at", Instant.now().toString());
                updateTask(task); append("task_update", str(task, "bridge_boot_id"), str(task, "world_session_id"), obj("transition_seq", task.get("version"), "task", task), false);
            }
            return null;
        });
    }
    public String instance() { return instance; }
    public synchronized String worldId(String privateKey) throws IOException {
        return transaction(() -> {
            String key = hash(privateKey), world = text("SELECT world_id FROM worlds WHERE key_hash=?", key);
            if (world == null) { world = "world-" + UUID.randomUUID(); execute("INSERT INTO worlds VALUES(?,?)", key, world); } return world;
        });
    }
    public synchronized JsonObject find(String world, String requestId) {
        try { require(scalar("SELECT count(*) FROM journal_retired_tasks WHERE world=? AND request_id=?", world, requestId) == 0, "GAME_TASK_HISTORY_EXPIRED"); }
        catch (SQLException error) { throw new IllegalStateException(io(error)); }
        try (PreparedStatement query = statement("SELECT body_hash,task FROM tasks WHERE world=? AND request_id=?", world, requestId); ResultSet rows = query.executeQuery()) {
            return rows.next() ? obj("hash", rows.getString(1), "task", parse(rows.getString(2))) : null;
        } catch (SQLException error) { throw new IllegalStateException(io(error)); }
    }
    /** Read-only proof in original context; no stored request is ever dispatched. */
    public synchronized JsonArray lookup(JsonArray ids) {
        require(ids.size() == 1, "GAME_LEDGER_QUERY_LIMIT"); JsonArray result = new JsonArray();
        try {
            for (JsonElement id : ids) {
                String found = text("SELECT task FROM tasks WHERE task_id=?", id.getAsString());
                result.add(obj("task_id", id, "status", found == null ? "missing" : "found", "task", found == null ? null : parse(found)));
            }
            return result;
        } catch (SQLException error) { throw new IllegalStateException(io(error)); }
    }
    /**
     * A missing row alone cannot prove that an action never happened: completed
     * history may have been retained elsewhere. Only a new, durable task-ID
     * tombstone, created atomically while both live and retired records are
     * absent, proves non-admission and also fences a delayed task_start.
     * Existing restore protection preserves these tombstones across rollback.
     */
    public synchronized JsonArray lookupForRecovery(JsonArray ids, String boot, String world) throws IOException {
        require(ids.size() == 1 && !maintenanceOnly, "GAME_LEDGER_QUERY_LIMIT");
        return transaction(() -> {
            require(Objects.equals(boot, text("SELECT value FROM metadata WHERE key='active_boot'"))
                    && Objects.equals(world, text("SELECT value FROM metadata WHERE key='active_world'")), "GAME_LEDGER_CONTEXT");
            String id = ids.get(0).getAsString(); require(id.matches("[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}"), "GAME_LEDGER_TASK_ID");
            String found = text("SELECT task FROM tasks WHERE task_id=?", id);
            JsonArray result = new JsonArray();
            if (found != null) { result.add(obj("task_id", id, "status", "found", "task", parse(found))); return result; }
            JsonObject proof = null;
            try (PreparedStatement query = statement("SELECT world,request_id,body_hash,summary FROM journal_retired_tasks WHERE task_id=?", id);
                 ResultSet rows = query.executeQuery()) {
                if (rows.next()) {
                    if ("admission-absence".equals(rows.getString(1))) {
                        proof = parse(rows.getString(4));
                        require(id.equals(rows.getString(2)) && hash(canonical(proof)).equals(rows.getString(3))
                                && "never_admitted".equals(str(proof,"kind")) && id.equals(str(proof,"task_id"))
                                && instance.equals(str(proof,"game_instance_id")), "GAME_JOURNAL_ADMISSION_FENCE_INVALID");
                    } else { result.add(obj("task_id", id, "status", "missing", "task", null)); return result; }
                }
            }
            if (proof == null) {
                require(scalar("SELECT count(*) FROM journal_retired_tasks") < JournalRetention.TOMBSTONE_LIMIT,
                        "GAME_RETENTION_TOMBSTONE_LIMIT");
                proof = obj("kind", "never_admitted", "fence_id", "admission-fence-" + UUID.randomUUID(),
                        "task_id", id, "game_instance_id", instance, "fenced_at", Instant.now().toString());
                execute("INSERT INTO journal_retired_tasks VALUES(?,?,?,?,?,?)", "admission-absence", id, id,
                        hash(canonical(proof)), System.currentTimeMillis(), canonical(proof));
            }
            JsonObject checked = proof.deepCopy(); checked.addProperty("checked_bridge_boot_id", boot);
            checked.addProperty("checked_world_session_id", world);
            result.add(obj("task_id", id, "status", "missing", "task", null, "admission_fence", checked)); return result;
        });
    }
    public synchronized void accept(String world, JsonObject request, JsonObject task) throws IOException { accept(world, request, task, null); }
    public synchronized void accept(String world, JsonObject request, JsonObject task, String boot) throws IOException {
        transaction(() -> {
            require(scalar("SELECT count(*) FROM tasks") < TASK_LIMIT, "GAME_LOCAL_TASK_LIMIT");
            require(find(world, str(request, "request_id")) == null, "GAME_LOCAL_DUPLICATE");
            require(scalar("SELECT count(*) FROM journal_retired_tasks WHERE task_id=?", str(task, "task_id")) == 0, "GAME_TASK_HISTORY_EXPIRED");
            insertTask(world, str(request, "request_id"), hash(canonical(request)), task);
            if (boot != null) append("task_update", boot, world, obj("transition_seq", task.get("version"), "task", task), true);
            return null;
        });
    }
    private void updateTask(JsonObject task) throws SQLException {
        String world = str(task, "world_session_id"), request = str(task, "request_id"), id = str(task, "task_id");
        JsonObject old = find(world, request); require(old != null, "GAME_LOCAL_TASK_UNKNOWN");
        JsonObject previous = old.getAsJsonObject("task");
        require(str(previous, "task_id").equals(id) && num(task, "version") == num(previous, "version") + 1
                && Set.of("accepted", "running").contains(str(previous, "state")), "GAME_LOCAL_TASK_VERSION");
        for (String field : List.of("bridge_boot_id", "world_id", "game_instance_id", "control_epoch", "goal", "created_at"))
            require(Objects.equals(previous.get(field), task.get(field)), "GAME_LOCAL_TASK_CONTEXT");
        require(Set.of("running", "succeeded", "failed", "cancelled", "rejected").contains(str(task, "state")), "GAME_LOCAL_TASK_STATE");
        execute("UPDATE tasks SET version=?,state=?,task=? WHERE task_id=?", num(task, "version"), str(task, "state"), json(task), id); transition(task);
    }
    public synchronized void update(JsonObject task) throws IOException { update(task, null); }
    public synchronized void update(JsonObject task, String boot) throws IOException {
        transaction(() -> { updateTask(task); if (boot != null) append("task_update", boot, str(task, "world_session_id"), obj("transition_seq", task.get("version"), "task", task), true); return null; });
    }
    /** Archive previous delivery contexts atomically. Never re-envelope historical facts. */
    public synchronized void activateContext(String boot, String world) throws IOException {
        transaction(() -> {
            String nextWorld = world == null ? "" : world;
            if (boot.equals(text("SELECT value FROM metadata WHERE key='active_boot'")) && nextWorld.equals(text("SELECT value FROM metadata WHERE key='active_world'"))) return null;
            long now = System.currentTimeMillis();
            execute("UPDATE contexts SET closed_at=?,reason=CASE WHEN boot=? THEN 'world_changed' ELSE 'bridge_restart' END WHERE closed_at IS NULL", now, boot);
            execute("UPDATE reliable SET archived_at=?,archive_reason=CASE WHEN boot=? THEN 'world_changed' ELSE 'bridge_restart' END WHERE acked_at IS NULL AND archived_at IS NULL AND NOT(boot=? AND world=?)", now, boot, boot, nextWorld);
            execute("UPDATE metadata SET value=? WHERE key='active_boot'", boot); execute("UPDATE metadata SET value=? WHERE key='active_world'", nextWorld);
            if (world != null) execute("INSERT INTO contexts VALUES(?,?,?,NULL,NULL) ON CONFLICT(boot,world) DO UPDATE SET closed_at=NULL,reason=NULL", boot, world, now);
            return null;
        });
    }
    private JsonObject append(String type, String boot, String world, JsonObject payload, boolean enforceWindow) throws SQLException {
        String stream = stream(type);
        require(scalar("SELECT count(*) FROM reliable") < RELIABLE_LIMIT, "GAME_LOCAL_HISTORY_LIMIT");
        boolean current = boot.equals(text("SELECT value FROM metadata WHERE key='active_boot'")) && world.equals(text("SELECT value FROM metadata WHERE key='active_world'"));
        // Before first context activation, stand-alone ledger callers can prepare a pending fixture.
        boolean unset = "".equals(text("SELECT value FROM metadata WHERE key='active_boot'"));
        if (enforceWindow && (current || unset)) require(scalar("SELECT count(*) FROM reliable WHERE acked_at IS NULL AND archived_at IS NULL") < 256, "GAME_RELIABLE_WINDOW_FULL");
        execute("INSERT INTO streams(boot,world,stream,issued) VALUES(?,?,?,1) ON CONFLICT(boot,world,stream) DO UPDATE SET issued=issued+1", boot, world, stream);
        long seq = scalar("SELECT issued FROM streams WHERE boot=? AND world=? AND stream=?", boot, world, stream);
        JsonObject value = payload.deepCopy(); value.addProperty("delivery_seq", seq); long now = System.currentTimeMillis();
        boolean archived = !current && !unset;
        execute("INSERT INTO reliable(rowid,boot,world,stream,delivery_seq,type,payload,created_at,archived_at,archive_reason,acked_at) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                nextHistoryId("reliable", "history_reliable_highwater"), boot, world, stream, seq, type, json(value), now, archived ? now : null, archived ? "late_historical_result" : null);
        return value;
    }
    public synchronized JsonObject reliable(String type, String boot, String world, JsonObject payload) throws IOException {
        return transaction(() -> append(type, boot, world, payload, true));
    }
    public synchronized List<JsonObject> pending(String boot, String world) {
        List<JsonObject> result = new ArrayList<>();
        try (PreparedStatement query = statement("SELECT type,stream,payload FROM reliable WHERE boot=? AND world=? AND acked_at IS NULL AND archived_at IS NULL ORDER BY stream,delivery_seq LIMIT 256", boot, world); ResultSet rows = query.executeQuery()) {
            while (rows.next()) result.add(obj("type", rows.getString(1), "boot", boot, "world", world, "stream", rows.getString(2), "payload", parse(rows.getString(3))));
            return result;
        } catch (SQLException error) { throw new IllegalStateException(io(error)); }
    }
    public synchronized void ack(String boot, String world, String stream, long through) throws IOException {
        transaction(() -> {
            require(through >= 0 && scalar("SELECT count(*) FROM streams WHERE boot=? AND world=? AND stream=? AND issued>=?", boot, world, stream, through) == 1, "GAME_ACK_OUT_OF_RANGE");
            execute("UPDATE streams SET acked=max(acked,?) WHERE boot=? AND world=? AND stream=?", through, boot, world, stream);
            execute("UPDATE reliable SET acked_at=coalesce(acked_at,?) WHERE boot=? AND world=? AND stream=? AND delivery_seq<=?", System.currentTimeMillis(), boot, world, stream, through);
            return null;
        });
    }
    /** Bounded local diagnostics. Does not expose tasks or raw game/server addresses. */
    public synchronized JsonObject status() {
        try { return obj("schema_version", SCHEMA_VERSION, "tasks", scalar("SELECT count(*) FROM tasks"),
                "pending", scalar("SELECT count(*) FROM reliable WHERE acked_at IS NULL AND archived_at IS NULL"),
                "archived_unacked", scalar("SELECT count(*) FROM reliable WHERE acked_at IS NULL AND archived_at IS NOT NULL"),
                "acknowledged", scalar("SELECT count(*) FROM reliable WHERE acked_at IS NOT NULL"), "retention_blocked", scalar("SELECT count(*) FROM reliable") >= RELIABLE_LIMIT); }
        catch (SQLException error) { throw new IllegalStateException(io(error)); }
    }
    /** Explicit local historical read, always includes original context and archive reason. */
    public synchronized JsonArray archivePage(String boot, String world, String stream, long after, int limit) {
        require(Set.of("events", "task_transitions").contains(stream) && after >= 0 && limit >= 1 && limit <= 100, "GAME_LOCAL_ARCHIVE_PAGE");
        JsonArray result = new JsonArray();
        try (PreparedStatement query = statement("SELECT delivery_seq,type,payload,archive_reason FROM reliable WHERE boot=? AND world=? AND stream=? AND archived_at IS NOT NULL AND delivery_seq>? ORDER BY delivery_seq LIMIT ?", boot, world, stream, after, limit); ResultSet rows = query.executeQuery()) {
            while (rows.next()) result.add(obj("boot", boot, "world", world, "stream", stream, "delivery_seq", rows.getLong(1), "type", rows.getString(2), "payload", parse(rows.getString(3)), "archive_reason", rows.getString(4)));
            return result;
        } catch (SQLException error) { throw new IllegalStateException(io(error)); }
    }
    /** All delivery rows and task versions are readable without acknowledging or replaying them. */
    public synchronized JsonObject historyPage(JsonObject params) {
        try { return JournalHistory.page(db, params); }
        catch (SQLException error) { throw new IllegalStateException(io(error)); }
    }
    public synchronized JsonObject retentionPlan(long now, Set<String> protectedTasks) throws IOException {
        require(maintenanceOnly, "GAME_JOURNAL_OFFLINE_REQUIRED");
        try { return JournalRetention.plan(db, instance, now, protectedTasks, "retention-" + UUID.randomUUID()); }
        catch (SQLException error) { throw io(error); }
    }
    public synchronized JsonObject applyRetention(JsonObject plan, String reviewedHash) throws IOException {
        require(maintenanceOnly, "GAME_JOURNAL_OFFLINE_REQUIRED");
        require(hash(canonical(plan)).equals(reviewedHash), "GAME_RETENTION_PLAN_HASH");
        try {
            JsonObject old = JournalRetention.previous(db, str(plan, "run_id"), reviewedHash);
            if (old != null) return old;
            JournalRetention.validatePlan(db, instance, plan);
            require(num(plan.getAsJsonObject("counts"), "events") + num(plan.getAsJsonObject("counts"), "tasks") > 0, "GAME_RETENTION_NOTHING_TO_APPLY");
            Path copy = backup();
            return transaction(() -> {
                JournalRetention.validatePlan(db, instance, plan);
                return JournalRetention.apply(db, plan, reviewedHash, copy.getFileName().toString());
            });
        } catch (SQLException error) { throw io(error); }
    }
    public synchronized JsonObject retentionStatus() throws IOException {
        require(maintenanceOnly, "GAME_JOURNAL_OFFLINE_REQUIRED");
        try { JsonObject value=JournalRetention.status(db);value.addProperty("game_instance_id",instance);return value; } catch (SQLException error) { throw io(error); }
    }
    /** Observe one committed run without applying or retrying a maintenance plan. */
    public synchronized JsonObject retentionResult(JsonObject plan,String reviewedHash) throws IOException {
        require(maintenanceOnly,"GAME_JOURNAL_OFFLINE_REQUIRED");
        require(str(plan,"game_instance_id").equals(instance),"GAME_RETENTION_DEPENDENCY_INSTANCE");
        require(hash(canonical(plan)).equals(reviewedHash),"GAME_RETENTION_PLAN_HASH");
        try {return JournalRetention.previous(db,str(plan,"run_id"),reviewedHash);}catch(SQLException error){throw io(error);}
    }

    /** A consistent native backup includes committed WAL; never copy an active main file. */
    public synchronized Path backup() throws IOException { return backup(db, directory, "snapshot"); }
    private static Path backupDirectory(Path directory, boolean create) throws IOException {
        Path backups = directory.resolve("backups");
        require(!Files.isSymbolicLink(backups), "GAME_LOCAL_BACKUP_PATH");
        if (create) Files.createDirectories(backups);
        require(backups.toRealPath().getParent().equals(directory.toRealPath()), "GAME_LOCAL_BACKUP_PATH"); return backups;
    }
    private static Path backup(Connection connection, Path directory, String prefix) throws IOException {
        Path backups = backupDirectory(directory, true);
        try (var files = Files.list(backups)) { require(files.filter(p -> p.getFileName().toString().endsWith(".sqlite3")).count() < 8, "GAME_LOCAL_BACKUP_LIMIT"); }
        Path target = backups.resolve(prefix + "-" + UUID.randomUUID() + ".sqlite3");
        try {
            int result = ((SQLiteConnection) connection).getDatabase().backup("main", target.toString(), null, 10, 20, 100);
            require(result == 0, "GAME_LOCAL_BACKUP_FAILED");
            try (FileChannel output = FileChannel.open(target, StandardOpenOption.WRITE)) { output.force(true); }
            JsonObject receipt = obj("schema_version", Integer.parseInt(readText(connection, "PRAGMA user_version")), "sha256", digest(target), "bytes", Files.size(target), "created_at", Instant.now().toString());
            writeDurably(target.resolveSibling(target.getFileName() + ".json"), GSON.toJson(receipt).getBytes(StandardCharsets.UTF_8));
            return target;
        } catch (SQLException error) { throw io(error); }
    }
    /** Offline-only same-installation restore. Ownership is acquired before any database access. */
    public static Path restore(Path directory, String backupName) throws IOException {
        return restore(directory, backupName, null);
    }
    public static Path restore(Path directory, String backupName, String reviewedHash) throws IOException {
        Path root = directory.toAbsolutePath().normalize(); require(backupName.matches("(?:snapshot|pre-restore|schema-v2)-[0-9a-f-]{36}\\.sqlite3"), "GAME_LOCAL_BACKUP_NAME");
        try (Ownership ignored = new Ownership(root)) {
            prepareNative(root); Path source = backupDirectory(root, false).resolve(backupName);
            require(!Files.isSymbolicLink(source) && source.toRealPath().getParent().equals(root.resolve("backups").toRealPath()), "GAME_LOCAL_BACKUP_PATH");
            JsonObject receipt = parse(Files.readString(source.resolveSibling(backupName + ".json"), StandardCharsets.UTF_8));
            require(Set.of(2L, (long) SCHEMA_VERSION).contains(num(receipt, "schema_version")) && str(receipt, "sha256").equals(digest(source)) && num(receipt, "bytes") == Files.size(source), "GAME_LOCAL_BACKUP_MISMATCH");
            require(reviewedHash == null || reviewedHash.equals(str(receipt, "sha256")), "GAME_LOCAL_BACKUP_MISMATCH");
            try (Connection incoming = connect(source, true); Connection current = connect(root.resolve("mc-control.sqlite3"), false)) {
                verifyBackup(incoming); verifyBackup(current);
                require(Long.parseLong(readText(incoming, "PRAGMA user_version")) == num(receipt, "schema_version"), "GAME_LOCAL_BACKUP_MISMATCH");
                require(readText(incoming, "SELECT value FROM metadata WHERE key='instance_id'").equals(readText(current, "SELECT value FROM metadata WHERE key='instance_id'")), "GAME_LOCAL_BACKUP_INSTANCE");
                Path before = backup(current, root, "pre-restore");
                try {
                    int result = ((SQLiteConnection) current).getDatabase().restore("main", source.toString(), null, 10, 20, 100);
                    require(result == 0, "GAME_LOCAL_RESTORE_FAILED"); verifyBackup(current);
                    try (Connection protection = connect(before, true)) {
                        if ("3".equals(readText(protection, "PRAGMA user_version"))) {
                            current.setAutoCommit(false);
                            try { JournalRetention.restoreProtection(current, protection); current.commit(); }
                            catch (Throwable error) { current.rollback(); throw error; }
                            finally { current.setAutoCommit(true); }
                        }
                    }
                    verifyBackup(current); return before;
                } catch (Throwable error) {
                    try {
                        require(((SQLiteConnection) current).getDatabase().restore("main", before.toString(), null, 10, 20, 100) == 0, "GAME_LOCAL_RESTORE_ROLLBACK_FAILED");
                        verifyBackup(current);
                    } catch (Throwable rollback) { error.addSuppressed(rollback); }
                    throw error;
                }
            }
        } catch (SQLException error) { throw io(error); }
        catch (ClassNotFoundException error) { throw new IOException("GAME_LOCAL_SQLITE_UNAVAILABLE", error); }
    }
    private static void verifyBackup(Connection connection) throws SQLException {
        require(Set.of("2", Integer.toString(SCHEMA_VERSION)).contains(readText(connection, "PRAGMA user_version")), "GAME_JOURNAL_VERSION");
        require("ok".equals(readText(connection, "PRAGMA quick_check")), "GAME_JOURNAL_INTEGRITY");
    }
    private static String readText(Connection connection, String sql) throws SQLException {
        try (Statement query = connection.createStatement(); ResultSet row = query.executeQuery(sql)) { require(row.next(), "GAME_JOURNAL_INTEGRITY"); return row.getString(1); }
    }
    private static String digest(Path file) throws IOException {
        try (InputStream input = Files.newInputStream(file)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256"); byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) >= 0) digest.update(buffer, 0, count); return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }
    private static void copyDurably(Path source, Path target) throws IOException {
        writeDurably(target, Files.readAllBytes(source));
    }
    private static void writeDurably(Path file, byte[] bytes) throws IOException {
        try (FileChannel output = FileChannel.open(file, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            ByteBuffer buffer = ByteBuffer.wrap(bytes); while (buffer.hasRemaining()) output.write(buffer); output.force(true);
        }
    }
    @Override public synchronized void close() throws IOException {
        if (closed) return; closed = true;
        try { db.close(); } catch (SQLException error) { throw io(error); } finally { ownership.close(); }
    }
    private static final class Ownership implements AutoCloseable {
        private final FileChannel owner; private final FileLock lock;
        Ownership(Path directory) throws IOException {
            owner = FileChannel.open(directory.resolve("owner.lock"), StandardOpenOption.CREATE, StandardOpenOption.WRITE);
            FileLock acquired;
            try { acquired = owner.tryLock(); } catch (OverlappingFileLockException error) { acquired = null; }
            catch (IOException error) { owner.close(); throw error; }
            if (acquired == null) { owner.close(); throw new IOException("GAME_LOCAL_STORE_BUSY"); } lock = acquired;
        }
        @Override public void close() throws IOException { try { lock.release(); } finally { owner.close(); } }
    }
}
