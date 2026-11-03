package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.io.IOException;
import java.net.URI;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.LongSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Bounded I/O actor. Game samples coalesce; side effects run only after durable acceptance. */
public final class BridgeCore implements AutoCloseable {
    private final GamePort port;
    private final LocalJournal journal;
    private final Wire wire = new Wire();
    private final LongSupplier clock;
    private final URI endpoint;
    private final ScheduledExecutorService actor;
    private final ExecutorService httpWorkers;
    private final HttpClient http;
    private final ExecutorService imageWorker = Executors.newSingleThreadExecutor(r -> { Thread t = new Thread(r, "mc-frame-encode-upload"); t.setDaemon(true); return t; });
    private final AtomicBoolean capturing = new AtomicBoolean();
    private long nextCapture;
    private final ArrayBlockingQueue<Runnable> inbox = new ArrayBlockingQueue<>(64);
    private final AtomicReference<JsonObject> sample = new AtomicReference<>();
    private final AtomicBoolean closing = new AtomicBoolean();
    private final AtomicInteger queuedSends = new AtomicInteger();
    private final AtomicLong generation = new AtomicLong();
    private final AtomicLong actorTickAt = new AtomicLong(), observationAt = new AtomicLong();
    private final AtomicLong maxActorGap = new AtomicLong(), maxObservationGap = new AtomicLong(), maxInboxWait = new AtomicLong();
    private final AtomicLong lastAdmission = new AtomicLong(), lastTaskCommit = new AtomicLong();
    private final AtomicReference<JsonObject> lastStop = new AtomicReference<>();
    private final AtomicReference<JsonObject> firstStopSinceAuto = new AtomicReference<>();
    private final Set<String> cancelledTasks = ConcurrentHashMap.newKeySet();
    private final String boot = "boot-" + UUID.randomUUID();
    private volatile String world, worldId, fault;
    private volatile Throwable failure;
    private volatile WebSocket socket;
    private volatile boolean acknowledged, connecting;
    private volatile JsonObject task;
    private JsonObject autoRequest, previousSample;
    private volatile JsonObject resumeRequest;
    private final PlayerLifeEvents lifeEvents = new PlayerLifeEvents();
    private String journalWorld;
    private boolean journalContextReady;
    private long nextConnect, nextState, nextHeartbeat, nextReliable, observationSeq, nextTaskDeadline;
    private long retryMs = 1000;
    private CompletableFuture<WebSocket> sends = CompletableFuture.completedFuture(null);
    public final ControlArbiter control;

    public BridgeCore(GamePort port, LocalJournal journal, URI endpoint) {
        this(port, journal, endpoint, () -> System.nanoTime() / 1_000_000);
    }
    public BridgeCore(GamePort port, LocalJournal journal, URI endpoint, LongSupplier clock) {
        this.port = port; this.journal = journal; this.endpoint = endpoint; this.clock = clock;
        require(Set.of("ws", "wss").contains(endpoint.getScheme()) && endpoint.getHost() != null && endpoint.getUserInfo() == null
                && endpoint.getRawQuery() == null && endpoint.getFragment() == null
                && "/api/dsh/game/bridge".equals(endpoint.getPath()), "GAME_ENDPOINT_INVALID");
        control = new ControlArbiter(clock, this::releaseRequested);
        actor = Executors.newSingleThreadScheduledExecutor(r -> new Thread(r, "mc-bridge-io"));
        httpWorkers = Executors.newFixedThreadPool(2, r -> { Thread t = new Thread(r, "mc-bridge-http"); t.setDaemon(true); return t; });
        http = HttpClient.newBuilder().executor(httpWorkers).connectTimeout(Duration.ofSeconds(5)).build();
    }
    private void releaseRequested() {
        long epoch = control.epoch(); port.execute(() -> control.release(epoch, port::releaseInputs));
    }
    private void cancelOnGameThread(long epoch, String reason, Runnable after) {
        JsonObject cancelled = markRevokedTask(epoch);
        port.execute(() -> {
            boolean released = control.release(epoch, () -> { port.cancel(reason); port.releaseInputs(); });
            finishRevokedTask(cancelled, released, reason);
            if (after != null) post(() -> { if (released && control.epoch() == epoch) after.run(); });
        });
    }
    private JsonObject markRevokedTask(long epoch) {
        JsonObject cancelled = task;
        if (cancelled == null || num(cancelled, "control_epoch") >= epoch) return null;
        cancelledTasks.add(str(cancelled, "task_id")); return cancelled;
    }
    private void finishRevokedTask(JsonObject cancelled, boolean released, String reason) {
        // The port may not have started and therefore has no completion callback.
        // Confirm cleanup first, then terminate only the original accepted task.
        if (released && cancelled != null && task == cancelled)
            completeTask(cancelled, obj("state", "cancelled", "reason", reason, "effect_status", "unknown"));
    }
    public void start() { actor.scheduleWithFixedDelay(this::tick, 0, 50, TimeUnit.MILLISECONDS); }
    public String instance() { return journal.instance(); }
    public String fault() { return fault; }
    /** Local bounded timing only; no database lock, filesystem or private payloads. */
    public JsonObject diagnostics() {
        JsonObject stopped = lastStop.get(), first = firstStopSinceAuto.get();
        return obj("max_actor_gap_ms", maxActorGap.get() / 1_000_000.0, "max_observation_gap_ms", maxObservationGap.get() / 1_000_000.0,
                "max_inbox_wait_ms", maxInboxWait.get() / 1_000_000.0, "last_admission_ms", lastAdmission.get() / 1_000_000.0,
                "last_task_commit_ms", lastTaskCommit.get() / 1_000_000.0, "last_stop", stopped == null ? null : stopped.deepCopy(),
                "first_stop_since_auto", first == null ? null : first.deepCopy(), "journal", journal.timings());
    }
    private static void gap(AtomicLong last, AtomicLong maximum) {
        long now = System.nanoTime(), previous = last.getAndSet(now);
        if (previous != 0) maximum.accumulateAndGet(Math.max(0, now - previous), Math::max);
    }
    /** Bounded diagnostic without filesystem paths, messages, or game/user data. */
    public String faultDetail() {
        Throwable cause = failure; if (cause == null) return null;
        for (int i = 0; i < 8 && cause.getCause() != null; i++) cause = cause.getCause();
        StackTraceElement[] stack = cause.getStackTrace();
        return cause.getClass().getSimpleName() + (stack.length == 0 ? "" : " at " + stack[0].getClassName()
                + "." + stack[0].getMethodName() + ":" + stack[0].getLineNumber());
    }
    public String boot() { return boot; }
    public long connectionGeneration() { return generation.get(); }
    public synchronized long latestObservationSeq() { return observationSeq; }
    private void post(Runnable action) {
        long posted = System.nanoTime();
        if (!closing.get() && !inbox.offer(() -> { maxInboxWait.accumulateAndGet(Math.max(0, System.nanoTime() - posted), Math::max); action.run(); })) fail("GAME_INBOX_FULL");
    }
    /** Called on the game thread; never performs disk or network I/O. */
    public synchronized void observe(Object worldObject, String privateWorldKey, JsonObject values) {
        gap(observationAt, maxObservationGap);
        String identity = privateWorldKey == null ? null : "world-" + hash(instance() + ":" + privateWorldKey).substring(0, 32);
        if (worldObject != observedWorld || !Objects.equals(identity, worldId)) {
            observedWorld = worldObject; worldId = identity; world = identity == null ? null : "world-session-" + UUID.randomUUID();
            observationSeq = 0; lifeEvents.reset(); long stoppedEpoch = control.world(world); sample.set(null);
            post(() -> { cancelOnGameThread(stoppedEpoch, "GAME_WORLD_CHANGED", null); closeSocket(); previousSample = null; });
        }
        if (world == null) return;
        JsonObject value = values.deepCopy();
        value.addProperty("schema_version", 1); value.addProperty("game_instance_id", instance()); value.addProperty("bridge_boot_id", boot);
        value.addProperty("world_id", worldId); value.addProperty("world_session_id", world);
        value.addProperty("connection_generation", Math.max(1, generation.get())); value.addProperty("seq", ++observationSeq);
        value.addProperty("observed_at", Instant.now().toString()); value.add("rule_fingerprint", JsonNull.INSTANCE);
        ControlArbiter.Stop stalled = control.observe(observationSeq); if (stalled != null) stopped(stalled.epoch(), stalled.reason());
        enrichControl(value); value.add("active_task_id", task == null ? JsonNull.INSTANCE : task.get("task_id"));
        sample.set(value);
        JsonObject acceptedTask = task;
        JsonObject life = lifeEvents.observe(value, acceptedTask == null ? null : str(acceptedTask, "task_id"));
        if (life != null) post(() -> {
            // Preserve the originating world even if it ended before the I/O actor ran.
            // LocalJournal archives late historical facts instead of re-enveloping them.
            try { journal.reliable("game_event", boot, str(life, "world_session_id"), life); nextReliable = 0; }
            catch (IOException error) { failure = error; fail("GAME_LOCAL_STORAGE_OR_PROTOCOL_ERROR"); }
        });
        if (!"gameplay".equals(str(value, "screen")) && control.mode() == ControlArbiter.Mode.AUTO) {
            JsonObject accepted = task;
            boolean expected = accepted != null && Set.of("inventory", "container").contains(str(value, "screen"))
                    && num(accepted, "control_epoch") == control.epoch() && port.allowsGui(accepted.deepCopy());
            boolean death = "death".equals(str(value, "screen")) && value.has("player")
                    && value.get("player").isJsonObject() && num(value.getAsJsonObject("player"), "health") <= 0;
            if (!expected) takeover(false, death ? "PLAYER_DEATH" : "GUI_BLOCKED");
        }
    }
    public JsonObject latestObservation() { JsonObject value = sample.get(); return value == null ? null : value.deepCopy(); }
    public String worldSession() { return world; }
    public boolean taskIdle() { return task == null; }
    public boolean preparingAuto() { return resumeRequest != null; }
    private Object observedWorld;
    private void enrichControl(JsonObject value) {
        value.addProperty("mode", control.mode().name()); value.addProperty("control_epoch", control.epoch());
        value.addProperty("inputs_released", control.released()); value.addProperty("automation_ready", control.ready());
        value.add("lease_remaining_ms", control.mode() == ControlArbiter.Mode.AUTO ? new JsonPrimitive(control.remaining()) : JsonNull.INSTANCE);
    }
    public void takeover(boolean manual, String reason) {
        resumeRequest = null;
        long stoppedEpoch = control.stop(manual ? ControlArbiter.Mode.MANUAL_COMMENTARY : ControlArbiter.Mode.PAUSED, reason);
        stopped(stoppedEpoch, reason);
    }
    /** Runtime adapters must renegotiate changed capabilities through the same connection authority. */
    public void capabilitiesChanged() {
        if (closing.get()) return;
        takeover(false, "GAME_CAPABILITIES_CHANGED");
        post(() -> { autoRequest = null; closeSocket(); });
    }
    private void stopped(long epoch, String reason) {
        JsonObject stopped = obj("epoch", epoch, "reason", reason); lastStop.set(stopped); firstStopSinceAuto.compareAndSet(null, stopped);
        cancelOnGameThread(epoch, reason, () -> {
            autoRequest = null; controlResult(obj("request_id", "local-" + UUID.randomUUID(), "operation_id", "local-" + UUID.randomUUID(), "stop_reason", reason), null);
        });
    }
    private void tick() {
        if (closing.get()) return;
        gap(actorTickAt, maxActorGap);
        try {
            String currentWorld = world;
            if (!journalContextReady || !Objects.equals(journalWorld, currentWorld)) {
                journal.activateContext(boot, currentWorld); journalWorld = currentWorld; journalContextReady = true;
            }
            ControlArbiter.Stop expired = control.expireAndStop(); if (expired != null) stopped(expired.epoch(), expired.reason());
            for (int i = 0; i < 16; i++) { Runnable message = inbox.poll(); if (message == null) break; message.run(); }
            if (fault != null) return;
            long now = clock.getAsLong();
            if (socket == null && !connecting && world != null && now >= nextConnect) connect();
            if (!acknowledged || socket == null || world == null) return;
            if (now >= nextState && queuedSends.get() < 2) {
                JsonObject latest = sample.get();
                if (latest != null) {
                    latest = latest.deepCopy(); enrichControl(latest); latest.addProperty("connection_generation", generation.get());
                    wire.validate("Observation", latest); send("snapshot", latest); detectEvents(latest); nextState = now + 200;
                }
            }
            if (now >= nextHeartbeat) { heartbeat(); nextHeartbeat = now + 1000; }
            if (now >= nextReliable) {
                for (JsonObject row : journal.pending(boot, world)) { if (queuedSends.get() >= 24) break; send(str(row, "type"), row.getAsJsonObject("payload")); }
                nextReliable = now + 1000;
            }
            JsonObject timedOut = task;
            if (timedOut != null && now >= nextTaskDeadline && cancelledTasks.add(str(timedOut, "task_id"))) {
                long taskEpoch = num(timedOut, "control_epoch");
                port.execute(() -> {
                    if (task != timedOut) return;
                    control.release(taskEpoch, () -> { port.cancel("TASK_TIMEOUT"); port.releaseInputs(); });
                    completeTask(timedOut, obj("state", "failed", "reason", "TASK_TIMEOUT", "effect_status", "unknown"));
                });
            }
        } catch (Json.Rejected error) {
            if (error.code.startsWith("GAME_LOCAL_") || error.code.startsWith("GAME_JOURNAL_") || error.code.equals("GAME_RELIABLE_WINDOW_FULL")) fail(error.code);
            else { takeover(false, error.code); closeSocket(); }
        } catch (Throwable error) { failure = error; fail("GAME_LOCAL_STORAGE_OR_PROTOCOL_ERROR"); }
    }
    private void connect() {
        connecting = true; long current = generation.incrementAndGet();
        http.newWebSocketBuilder().connectTimeout(Duration.ofSeconds(5)).buildAsync(endpoint, new WebSocket.Listener() {
            private final StringBuilder fragments = new StringBuilder();
            private int bytes;
            @Override public void onOpen(WebSocket ws) { ws.request(1); post(() -> {
                if (current != generation.get() || closing.get()) { ws.abort(); return; }
                socket = ws; connecting = false; acknowledged = false; sends = CompletableFuture.completedFuture(ws); retryMs = 1000; nextState = 0;
                JsonObject capabilities = port.capabilities(instance()).deepCopy();
                capabilities.getAsJsonObject("features").addProperty("journal_history", true);
                capabilities.getAsJsonObject("features").addProperty("journal_maintenance_history", true);
                send("hello", obj("capabilities", capabilities, "mode", control.mode().name(),
                        "control_epoch", control.epoch(), "world_session_id", world));
            }); }
            @Override public CompletionStage<?> onText(WebSocket ws, CharSequence text, boolean last) {
                bytes += text.toString().getBytes(StandardCharsets.UTF_8).length;
                if (bytes > Wire.MAX_BYTES) { ws.abort(); disconnected(current); return null; }
                fragments.append(text);
                if (last) { String value = fragments.toString(); fragments.setLength(0); bytes = 0;
                    post(() -> { if (socket == ws && current == generation.get()) receive(wire.incoming(value)); }); }
                ws.request(1); return null;
            }
            @Override public CompletionStage<?> onBinary(WebSocket ws, ByteBuffer data, boolean last) { ws.abort(); disconnected(current); return null; }
            @Override public CompletionStage<?> onClose(WebSocket ws, int status, String reason) { disconnected(current); return null; }
            @Override public void onError(WebSocket ws, Throwable error) { disconnected(current); }
        }).whenComplete((ws, error) -> { if (error != null) disconnected(current); });
    }
    private void disconnected(long current) {
        if (current != generation.get() || closing.get()) return;
        long stoppedEpoch = control.stop(ControlArbiter.Mode.PAUSED, "DISCONNECTED");
        post(() -> { if (current != generation.get()) return; connecting = false; socket = null; acknowledged = false; queuedSends.set(0);
            nextConnect = clock.getAsLong() + retryMs; retryMs = Math.min(15000, retryMs * 2); autoRequest = null;
            cancelOnGameThread(stoppedEpoch, "DISCONNECTED", null); });
    }
    private void closeSocket() {
        resumeRequest = null;
        WebSocket prior = socket; socket = null; connecting = false; acknowledged = false; generation.incrementAndGet(); queuedSends.set(0);
        if (prior != null) prior.abort(); nextConnect = clock.getAsLong() + 1000;
    }
    private void send(String type, JsonObject payload) {
        WebSocket ws = socket; if (ws == null) return;
        JsonObject frame = obj("protocol_version", "1.0", "type", type, "message_id", "message-" + UUID.randomUUID(),
                "game_instance_id", instance(), "bridge_boot_id", boot, "connection_generation", generation.get(), "sent_at", Instant.now().toString(), "payload", payload);
        wire.validate("BridgeEnvelope", frame); String text = GSON.toJson(frame);
        require(text.getBytes(StandardCharsets.UTF_8).length <= Wire.MAX_BYTES && queuedSends.get() < 32, "GAME_SEND_BACKPRESSURE");
        queuedSends.incrementAndGet(); long current = generation.get();
        sends = sends.thenCompose(ignored -> ws.sendText(text, true)).whenComplete((ignored, error) -> {
            if (current == generation.get()) queuedSends.decrementAndGet(); if (error != null) disconnected(current);
        });
    }
    private void receive(JsonObject frame) {
        require(str(frame, "game_instance_id").equals(instance()) && str(frame, "bridge_boot_id").equals(boot)
                && num(frame, "connection_generation") == generation.get(), "GAME_STALE_CONNECTION");
        String type = str(frame, "type"); JsonObject p = frame.getAsJsonObject("payload");
        if (type.equals("hello_ack")) {
            require(!acknowledged, "GAME_DUPLICATE_HELLO_ACK"); control.attach(str(p, "controller_session_id"));
            acknowledged = true; nextState = nextHeartbeat = nextReliable = 0; return;
        }
        require(acknowledged, "GAME_HELLO_REQUIRED");
        switch (type) {
            case "snapshot_request" -> nextState = 0;
            case "heartbeat" -> { }
            case "ack" -> { require(str(p, "world_session_id").equals(world), "GAME_WORLD_CHANGED");
                journalAck(p); }
            case "control_request" -> requestControl(p);
            case "lease_grant" -> {
                // Revocation can race a grant already in transit. A stale grant cannot
                // restore AUTO or replace a deliberate manual mode with another stop.
                boolean first;
                try { first = control.grant(str(p, "controller_session_id"), str(p, "lease_id"), num(p, "control_epoch"),
                        num(p, "grant_seq"), num(p, "based_on_heartbeat_seq"), num(p, "ttl_ms")); }
                catch (Json.Rejected stale) {
                    if (Set.of("GAME_LEASE_EXPIRED", "GAME_LEASE_CONTEXT", "GAME_LEASE_SEQUENCE", "GAME_HEARTBEAT_REFERENCE_EXPIRED", "GAME_CLIENT_TICK_STALLED").contains(stale.code)) return;
                    throw stale;
                }
                if (first && autoRequest != null) { controlResult(autoRequest, null); autoRequest = null; nextState = 0; }
            }
            case "task_start" -> startTask(p);
            case "task_cancel" -> { require(str(p, "controller_session_id").equals(control.controller()), "GAME_CONTROLLER_CHANGED");
                JsonObject cancelled = task;
                if (cancelled != null && str(cancelled, "task_id").equals(str(p, "task_id"))) {
                    cancelledTasks.add(str(cancelled, "task_id"));
                    long cancelledEpoch = control.epoch();
                    port.execute(() -> { if (task != cancelled) return;
                        control.release(cancelledEpoch, () -> { port.cancel(str(p, "reason")); port.releaseInputs(); });
                        completeTask(cancelled, obj("state", "cancelled", "reason", p.get("reason"), "effect_status", "unknown")); });
                } }
            case "query" -> query(p);
            case "protocol_error" -> { takeover(false, "CONTROLLER_PROTOCOL_ERROR"); closeSocket(); }
            default -> throw new Json.Rejected("GAME_UNEXPECTED_MESSAGE");
        }
    }
    private void journalAck(JsonObject p) { try { journal.ack(boot, world, str(p, "ack_kind"), num(p, "through_seq")); } catch (IOException error) { throw new IllegalStateException(error); } }
    private void requestControl(JsonObject p) {
        require(str(p, "controller_session_id").equals(control.controller()), "GAME_CONTROLLER_CHANGED");
        if (!str(p, "target_mode").equals("AUTO")) {
            resumeRequest = null;
            autoRequest = null; long stoppedEpoch = control.stop(ControlArbiter.Mode.valueOf(str(p, "target_mode")), "CONTROL_CHANGED");
            JsonObject cancelled = markRevokedTask(stoppedEpoch);
            port.execute(() -> {
                boolean released = control.release(stoppedEpoch, () -> { port.cancel("CONTROL_CHANGED"); port.releaseInputs(); });
                finishRevokedTask(cancelled, released, "CONTROL_CHANGED");
                post(() -> { controlResult(p, released && control.epoch() == stoppedEpoch ? null : "GAME_CONTROL_CONFLICT"); nextState = 0; });
            });
            return;
        }
        try {
            require(str(p, "bridge_boot_id").equals(boot), "GAME_BOOT_CHANGED");
            JsonObject features = port.capabilities(instance()).getAsJsonObject("features");
            require(features.get("local_takeover").getAsBoolean() && features.get("cancel_all").getAsBoolean(),
                    "GAME_EXECUTOR_ADAPTER_NOT_BOUND");
            JsonObject latest = sample.get(); require(task == null && latest != null, "GAME_PRECONDITION_FAILED");
            if (!"gameplay".equals(str(latest, "screen"))) {
                boolean resume = "menu".equals(str(latest,"screen")) && features.has("autonomous_resume") && features.get("autonomous_resume").getAsBoolean();
                boolean respawn = "death".equals(str(latest,"screen")) && features.has("autonomous_respawn") && features.get("autonomous_respawn").getAsBoolean();
                require((resume || respawn) && resumeRequest == null
                        && control.mode() == ControlArbiter.Mode.PAUSED && control.released()
                        && control.epoch() == num(p, "expected_control_epoch") && world.equals(str(p, "world_session_id")),
                        "GAME_PRECONDITION_FAILED");
                JsonObject pending = p.deepCopy(); resumeRequest = pending;
                port.execute(() -> {
                    synchronized (control) {
                        if (resumeRequest != pending) return;
                        if (control.mode() != ControlArbiter.Mode.PAUSED || control.epoch() != num(pending, "expected_control_epoch")
                                || !control.released() || task != null || !Objects.equals(world,str(pending,"world_session_id"))) {
                            post(() -> { if (resumeRequest == pending) { resumeRequest = null; controlResult(pending,"GAME_CONTROL_CONFLICT"); } }); return;
                        }
                        port.resumeAuto(() -> post(() -> {
                            // Pause policy uses this same monitor: do not leave
                            // a PAUSED/no-pending gap after ordinary respawn.
                            synchronized (control) {
                                if (resumeRequest != pending) return;
                                resumeRequest = null; requestControl(pending);
                            }
                        }), error -> post(() -> {
                            if (resumeRequest != pending) return;
                            resumeRequest = null; controlResult(pending,error);
                        }));
                    }
                });
                return;
            }
            firstStopSinceAuto.set(null);
            control.beginAuto(str(p, "controller_session_id"), str(p, "world_session_id"), num(p, "expected_control_epoch"), true);
            autoRequest = p.deepCopy(); heartbeat(); controlResult(p, null); nextState = 0;
        } catch (Json.Rejected error) { controlResult(p, error.code); }
    }
    private void heartbeat() {
        long seq = control.heartbeat(); JsonObject latest = sample.get();
        send("heartbeat", obj("heartbeat_seq", seq, "controller_session_id", control.controller(), "control_epoch", control.epoch(),
                "last_seq", latest == null ? null : num(latest, "seq"), "lease_id", control.lease(),
                "grant_seq", control.grantSeq() == 0 ? null : control.grantSeq(), "automation_ready", control.ready()));
    }
    private void controlResult(JsonObject request, String error) {
        if (!acknowledged || world == null) return;
        JsonObject result = obj("operation_id", request.get("operation_id"), "request_id", request.get("request_id"),
                "world_session_id", world, "mode", control.mode().name(), "control_epoch", control.epoch(), "inputs_released", control.released(),
                "automation_ready", control.ready(), "lease_id", control.lease(),
                "heartbeat_seq", control.mode() == ControlArbiter.Mode.AUTO ? control.lastHeartbeat() : null, "error", error);
        if (request.has("stop_reason")) result.add("stop_reason", request.get("stop_reason"));
        send("control_result", result);
    }
    private void startTask(JsonObject p) {
        JsonObject request = p.getAsJsonObject("request"); String worldAtStart = str(request, "world_session_id");
        JsonObject prior = journal.find(worldAtStart, str(request, "request_id"));
        if (prior != null) { require(str(prior, "hash").equals(hash(canonical(request)))
                && str(prior.getAsJsonObject("task"), "task_id").equals(str(p, "task_id"))
                && Objects.equals(prior.getAsJsonObject("task").get("base_target"), p.get("base_target")), "GAME_REQUEST_CONFLICT"); return; }
        try {
            require(task == null && boot.equals(str(request, "bridge_boot_id")), "GAME_TASK_BUSY_OR_BOOT_CHANGED");
            control.authorize(str(p, "controller_session_id"), str(p, "lease_id"), worldAtStart, num(p, "control_epoch"),
                    num(request, "based_on_seq"), num(request, "accept_within_ms"));
            require(num(request, "expected_control_epoch") == num(p, "control_epoch"), "GAME_CONTROL_CONFLICT");
            BaseTarget base = BaseTarget.resolve(request.getAsJsonObject("goal"), p.get("base_target"), request.get("base_ref"), sample.get());
            String now = Instant.now().toString(); JsonObject created = obj("task_id", p.get("task_id"), "game_instance_id", instance(),
                    "bridge_boot_id", boot, "world_id", worldId, "world_session_id", worldAtStart, "request_id", request.get("request_id"),
                    "control_epoch", request.get("expected_control_epoch"), "version", 1, "goal", request.get("goal"), "state", "accepted",
                    "created_at", now, "updated_at", now, "reason", null, "effect_status", "unknown", "evidence", new JsonArray());
            if (base != null) created.add("base_target", base.json());
            wire.validate("Task", created);
            long beganAcceptance = System.nanoTime();
            try { journal.accept(worldAtStart, request, created, boot); }
            finally { lastAdmission.set(Math.max(0, System.nanoTime() - beganAcceptance)); }
            task = created;
            nextReliable = 0; nextTaskDeadline = clock.getAsLong() + num(request, "max_duration_ms");
            // Revocation may finish while journal.accept is on disk, before task
            // becomes visible to the stop handler. Reconcile that accepted task
            // against the current epoch before scheduling either execution step.
            long currentEpoch = control.epoch();
            if (currentEpoch != num(created, "control_epoch")) {
                JsonObject stopped = lastStop.get();
                String reason = stopped != null && num(stopped, "epoch") == currentEpoch
                        ? str(stopped, "reason") : "CONTROL_REVOKED";
                cancelOnGameThread(currentEpoch, reason, null); return;
            }
            long executionDeadline = nextTaskDeadline;
            port.execute(() -> {
                try {
                    // The original observation fences admission above. Once accepted
                    // durably, recheck execution against fresh game-thread facts;
                    // disk/queue time must not turn the admission window into a
                    // second deadline for an already accepted task.
                    authorizeExecution(p, request, worldAtStart, executionDeadline);
                    post(() -> { if (task == created && !cancelledTasks.contains(str(created, "task_id"))) { created.addProperty("state", "running"); created.addProperty("version", 2);
                        created.addProperty("updated_at", Instant.now().toString()); persistTask(created);
                        port.execute(() -> {
                            if (task != created || cancelledTasks.contains(str(created, "task_id"))) return;
                            try {
                                authorizeExecution(p, request, worldAtStart, executionDeadline);
                                port.start(created.deepCopy(), control, result -> completeTask(created, result));
                            } catch (Json.Rejected error) {
                                if (control.epoch() == num(created, "control_epoch")) {
                                    control.release(num(created, "control_epoch"), port::releaseInputs);
                                    completeTask(created, obj("state", "failed", "reason", error.code, "effect_status", "unknown"));
                                }
                            } catch (RuntimeException error) { control.release(num(created, "control_epoch"), port::releaseInputs);
                                completeTask(created, obj("state", "failed", "reason", LocalTaskFailure.startReason(error), "effect_status", "unknown")); }
                        }); } });
                } catch (Json.Rejected error) {
                    if (control.epoch() == num(created, "control_epoch"))
                        completeTask(created, obj("state", "failed", "reason", error.code, "effect_status", "unknown"));
                }
            });
        } catch (IOException error) { throw new IllegalStateException(error); }
    }
    private void authorizeExecution(JsonObject command, JsonObject request, String worldAtStart, long deadline) {
        require(clock.getAsLong() < deadline, "TASK_TIMEOUT");
        JsonObject current = sample.get();
        require(current != null && worldAtStart.equals(str(current, "world_session_id"))
                && "gameplay".equals(str(current, "screen")), "GAME_PRECONDITION_FAILED");
        control.authorize(str(command, "controller_session_id"), str(command, "lease_id"), worldAtStart, num(command, "control_epoch"),
                num(current, "seq"), num(request, "accept_within_ms"));
        JsonObject checked = port.check(request.getAsJsonObject("goal"),
                BaseTarget.resolve(request.getAsJsonObject("goal"), command.get("base_target"), request.get("base_ref"), current)); require(checked.get("allowed").getAsBoolean(),
                nullable(checked, "reason") == null ? "GAME_PRECONDITION_FAILED" : str(checked, "reason"));
    }
    private void completeTask(JsonObject expected, JsonObject result) {
        post(() -> { if (task != expected) return;
            for (String field : List.of("state", "reason", "effect_status")) expected.add(field, result.has(field) ? result.get(field) : JsonNull.INSTANCE);
            expected.addProperty("version", num(expected, "version") + 1); expected.addProperty("updated_at", Instant.now().toString());
            expected.add("evidence", result.has("evidence") ? result.get("evidence") : new JsonArray()); persistTask(expected); task = null;
            cancelledTasks.remove(str(expected, "task_id"));
        });
    }
    private void persistTask(JsonObject value) {
        long began = System.nanoTime();
        try { wire.validate("Task", value); journal.update(value, boot); nextReliable = 0; } catch (IOException error) { throw new IllegalStateException(error); }
        finally { lastTaskCommit.set(Math.max(0, System.nanoTime() - began)); }
    }
    private void query(JsonObject p) {
        JsonObject request = p.getAsJsonObject("request");
        require(boot.equals(str(request, "bridge_boot_id")) && Objects.equals(world, str(request, "world_session_id")), "GAME_QUERY_CONTEXT");
        String queryWorld = world; String created = Instant.now().toString();
        if (Set.of("observation", "frame").contains(str(request, "kind"))) { captureQuery(p, queryWorld, created); return; }
        if (str(request, "kind").equals("journal_history")) {
            require(control.mode() != ControlArbiter.Mode.AUTO && control.released(), "GAME_HISTORY_MODE_BLOCKED");
            JsonObject result = journal.historyPage(request.getAsJsonObject("params"));
            JsonObject latest = sample.get();
            result.addProperty("kind", "journal_history"); result.addProperty("game_instance_id", instance());
            result.addProperty("world_session_id", queryWorld); result.addProperty("based_on_seq", latest == null ? 0 : num(latest, "seq"));
            wire.validate("JournalHistoryResult", result);
            send("query_result", obj("operation_id", p.get("operation_id"), "request_id", request.get("request_id"), "kind", "query",
                "state", "succeeded", "created_at", created, "updated_at", Instant.now().toString(), "result", result, "error", null));
            return;
        }
        if (str(request, "kind").equals("task_ledger")) {
            require(control.mode() != ControlArbiter.Mode.AUTO && control.released(), "GAME_RECOVERY_MODE_BLOCKED");
            JsonObject latest = sample.get();
            JsonObject result = obj("kind", "task_ledger", "game_instance_id", instance(), "world_session_id", queryWorld,
                    "based_on_seq", latest == null ? 0 : num(latest, "seq"),
                    "entries", journal.lookup(request.getAsJsonObject("params").getAsJsonArray("task_ids")));
            wire.validate("TaskLedgerResult", result);
            send("query_result", obj("operation_id", p.get("operation_id"), "request_id", request.get("request_id"), "kind", "query",
                    "state", "succeeded", "created_at", created, "updated_at", Instant.now().toString(), "result", result, "error", null));
            return;
        }
        long queryConnection = generation.get();
        port.execute(() -> {
            JsonObject result = null; String error = null;
            try {
                require(Objects.equals(world, queryWorld) && generation.get() == queryConnection && acknowledged, "GAME_QUERY_CONTEXT");
                String kind = str(request, "kind");
                result = switch (kind) {
                    case "check_action" -> {
                        JsonObject params = request.getAsJsonObject("params");
                        BaseTarget base = BaseTarget.resolve(params.getAsJsonObject("goal"), p.get("base_target"), params.get("base_ref"), sample.get());
                        JsonObject checked = port.check(params.getAsJsonObject("goal"), base);
                        if (base != null) checked.add("base_target", base.json());
                        yield checked;
                    }
                    case "recipe" -> port.recipe(request.getAsJsonObject("params"));
                    default -> throw new Json.Rejected("GAME_CAPABILITY_UNAVAILABLE");
                };
                result.addProperty("kind", kind); result.addProperty("world_session_id", queryWorld);
                JsonObject latest = sample.get(); result.addProperty("based_on_seq", latest == null ? 0 : num(latest, "seq"));
                if (kind.equals("recipe")) wire.validate("RecipeResult", result);
            } catch (Json.Rejected failure) { error = failure.code; }
            catch (RuntimeException failure) { error = "GAME_QUERY_FAILED"; }
            JsonObject completed = obj("operation_id", p.get("operation_id"), "request_id", request.get("request_id"), "kind", "query",
                    "state", error == null ? "succeeded" : "failed", "created_at", created, "updated_at", Instant.now().toString(), "result", result, "error", error);
            post(() -> { if (Objects.equals(world, queryWorld) && generation.get() == queryConnection && acknowledged) send("query_result", completed); });
        });
    }
    private void captureQuery(JsonObject p, String queryWorld, String created) {
        JsonObject request = p.getAsJsonObject("request"); long connection = generation.get();
        if (clock.getAsLong() < nextCapture || !capturing.compareAndSet(false, true)) {
            replyCapture(p, queryWorld, connection, created, null, "GAME_FRAME_CAPTURE_BUSY"); return;
        }
        nextCapture = clock.getAsLong() + 1000;
        port.execute(() -> {
            try {
                require(Objects.equals(world, queryWorld) && generation.get() == connection && acknowledged, "GAME_QUERY_CONTEXT");
                JsonObject latest = sample.get(); require(latest != null, "GAME_STATE_UNAVAILABLE");
                FrameEncoder.Capture capture = port.captureFrame();
                JsonObject metadata = obj("frame_id", "frame-" + UUID.randomUUID(), "operation_id", p.get("operation_id"),
                        "bridge_boot_id", boot, "world_session_id", queryWorld, "source_seq", latest.get("seq"),
                        "captured_at", Instant.now().toString(), "width", capture.width(), "height", capture.height());
                imageWorker.execute(() -> {
                    try {
                        require(Objects.equals(world, queryWorld) && generation.get() == connection && acknowledged, "GAME_QUERY_CONTEXT");
                        FrameUpload.send(http, endpoint, metadata, FrameEncoder.jpeg(capture));
                        JsonObject result = metadata.deepCopy(); result.remove("operation_id"); result.remove("bridge_boot_id"); result.add("kind", request.get("kind"));
                        replyCapture(p, queryWorld, connection, created, result, null);
                    } catch (Json.Rejected error) { replyCapture(p, queryWorld, connection, created, null, error.code); }
                    catch (Exception error) { replyCapture(p, queryWorld, connection, created, null, "GAME_FRAME_UPLOAD_FAILED"); }
                    finally { capturing.set(false); }
                });
            } catch (Json.Rejected error) { capturing.set(false); replyCapture(p, queryWorld, connection, created, null, error.code); }
            catch (RuntimeException error) { capturing.set(false); replyCapture(p, queryWorld, connection, created, null, "GAME_FRAME_CAPTURE_FAILED"); }
        });
    }
    private void replyCapture(JsonObject p, String queryWorld, long connection, String created, JsonObject result, String error) {
        post(() -> { if (!Objects.equals(world, queryWorld) || generation.get() != connection || !acknowledged) return;
            send("query_result", obj("operation_id", p.get("operation_id"), "request_id", p.getAsJsonObject("request").get("request_id"), "kind", "query",
                    "state", error == null ? "succeeded" : "failed", "created_at", created, "updated_at", Instant.now().toString(), "result", result, "error", error)); });
    }
    private void detectEvents(JsonObject latest) throws IOException {
        if (previousSample != null && str(previousSample, "world_session_id").equals(world)) {
            if (!latest.get("inventory").equals(previousSample.get("inventory"))) event("inventory_changed", "normal", latest, obj("inventory", latest.get("inventory")));
            JsonObject current = latest.getAsJsonObject("player"), previous = previousSample.getAsJsonObject("player");
            if (current != null && previous != null && !current.get("health").isJsonNull() && !previous.get("health").isJsonNull()
                    && current.get("health").getAsDouble() < previous.get("health").getAsDouble()) event("damage", "important", latest, obj("health", current.get("health")));
        }
        previousSample = latest.deepCopy();
    }
    private void event(String kind, String severity, JsonObject latest, JsonObject data) throws IOException {
        journal.reliable("game_event", boot, world, obj("event_id", "event-" + UUID.randomUUID(), "world_session_id", world,
                "seq", latest.get("seq"), "occurred_at", latest.get("observed_at"), "kind", kind, "severity", severity,
                "task_id", task == null ? null : task.get("task_id"), "data", data)); nextReliable = 0;
    }
    private void fail(String code) {
        if (fault != null) return;
        fault = code; control.stop(ControlArbiter.Mode.PAUSED, code); port.execute(() -> port.cancel(code));
        closeSocket();
    }
    @Override public void close() {
        if (!closing.compareAndSet(false, true)) return;
        control.stop(ControlArbiter.Mode.PAUSED, "SHUTDOWN"); port.execute(() -> port.cancel("SHUTDOWN")); closeSocket(); actor.shutdown();
        if (!Thread.currentThread().getName().equals("mc-bridge-io")) try { actor.awaitTermination(5, TimeUnit.SECONDS); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        imageWorker.shutdownNow(); http.shutdownNow(); httpWorkers.shutdownNow(); try { journal.close(); } catch (IOException error) { fault = "GAME_JOURNAL_CLOSE_FAILED"; }
    }
}
