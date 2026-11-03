package dev.aitalkstreamer.mc.neoforge;

import java.util.Objects;

/** Recovery allowances belong to the accepted task, including its survival children. */
final class NativeRouteRecovery {
    static final int MAX_ATTEMPTS = 4;
    static final int MAX_TOTAL_LANDING_TICKS = 40;
    private String taskId;
    private Object world, player, connection;
    private int attempts, landingTicks, episodeTicks, episodes;
    private boolean waiting;

    void bind(String id, Object world, Object player, Object connection) {
        if (!Objects.equals(taskId,id) || this.world!=world || this.player!=player || this.connection!=connection) {
            attempts=landingTicks=episodes=0;
        }
        taskId=id;this.world=world;this.player=player;this.connection=connection;
        waiting=false;episodeTicks=0;
    }
    boolean admitRoute() {
        if (attempts>=MAX_ATTEMPTS) return false;
        attempts++;return true;
    }
    NativeEscapeLanding.State landing(boolean grounded, boolean water, boolean lava) {
        if (!waiting) { waiting=true;episodeTicks=0;episodes++; }
        var state=NativeEscapeLanding.observe(grounded,water,lava,episodeTicks);
        if (state==NativeEscapeLanding.State.WAITING) {
            if (episodeTicks>=NativeEscapeLanding.MAX_TICKS || landingTicks>=MAX_TOTAL_LANDING_TICKS)
                state=NativeEscapeLanding.State.TIMED_OUT;
            else { episodeTicks++;landingTicks++; }
        }
        if (state!=NativeEscapeLanding.State.WAITING) waiting=false;
        return state;
    }
    boolean waiting() { return waiting; }
    int attempts() { return attempts; }
    int landingTicks() { return landingTicks; }
    int episodeTicks() { return episodeTicks; }
    int episodes() { return episodes; }
}
