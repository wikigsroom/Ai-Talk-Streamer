package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import java.util.function.Consumer;

/** All game-object access is on execute()/the client thread. Callbacks carry immutable JSON. */
public interface GamePort {
    void execute(Runnable action);
    void releaseInputs();
    JsonObject capabilities(String instance);
    JsonObject check(JsonObject goal);
    default JsonObject check(JsonObject goal, BaseTarget base) {
        Json.require(base == null && !Json.str(goal, "skill").equals("return_base"), "GAME_BASE_ADAPTER_NOT_BOUND");
        return check(goal);
    }
    default JsonObject recipe(JsonObject params) { throw new Json.Rejected("GAME_CAPABILITY_UNAVAILABLE"); }
    default FrameEncoder.Capture captureFrame() { throw new Json.Rejected("GAME_CAPABILITY_UNAVAILABLE"); }
    /** Client-thread check of this task's actual GUI objects, never a transport permission flag. */
    default boolean allowsGui(JsonObject acceptedTask) { return false; }
    /** Only the native adapter can resume an ordinary owned singleplayer pause.
     * Completion requires a subsequent real gameplay sample; this grants no lease. */
    default void resumeAuto(Runnable ready, Consumer<String> failed) { failed.accept("GAME_PRECONDITION_FAILED"); }
    void start(JsonObject task, ControlArbiter control, Consumer<JsonObject> completed);
    void cancel(String reason);
}
