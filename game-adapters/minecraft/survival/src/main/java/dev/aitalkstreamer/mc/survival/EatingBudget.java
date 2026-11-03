package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** One refill episode survives task reselection; only confirmed full hunger starts a new episode. */
public final class EatingBudget {
    public static final long TOTAL_MS = 120000, BITE_MS = 10000;
    public static final int MAX_ATTEMPTS = 20;
    private final long started;
    private long lastNow, biteAt;
    private int attempts, initialFood, nutrition;
    private boolean bite, issued, inventory, consumed, full;
    private int serverFood = -1;
    public EatingBudget(long now) { if (now < 0) throw new IllegalArgumentException(); started = lastNow = now; }
    public void check(long now) {
        if (now < lastNow) throw new IllegalArgumentException("Clock regressed"); lastNow = now;
        if (now - started >= TOTAL_MS || bite && now - biteAt >= BITE_MS) throw new LocalTaskFailure(EATING_SERVER_TIMEOUT);
    }
    public void begin(long now, int food, int nutrition) {
        check(now);
        if (bite || full || attempts >= MAX_ATTEMPTS) throw new LocalTaskFailure(EATING_LIMIT);
        if (food < 0 || food >= 20 || nutrition < 1 || nutrition > 20) throw new IllegalArgumentException("Invalid food facts");
        attempts++; bite = true; biteAt = now; initialFood = food; this.nutrition = nutrition;
        issued = inventory = consumed = false; serverFood = -1;
    }
    public void issue(long now) {
        check(now); if (!bite || issued) throw new IllegalStateException("GAME_EATING_ALREADY_ISSUED"); issued = true;
    }
    public void health(long now, int food) {
        check(now); if (bite && issued && food >= 0 && food <= 20) serverFood = food;
    }
    public void inventory(long now, boolean consumed) {
        check(now); if (!bite || consumed && !issued) throw new IllegalStateException("GAME_EATING_NOT_ISSUED");
        if (inventory && this.consumed != consumed) throw new IllegalStateException("GAME_EATING_RESULT_CHANGED");
        inventory = true; this.consumed = consumed;
    }
    public boolean resolved(long now) {
        check(now); return bite && inventory && (!consumed || serverFood >= Math.min(20, initialFood + nutrition));
    }
    public void restored(long now) {
        if (!resolved(now)) throw new IllegalStateException("GAME_EATING_NOT_CONFIRMED");
        full = consumed && serverFood == 20; bite = false;
    }
    public boolean full() { return full; }
}
