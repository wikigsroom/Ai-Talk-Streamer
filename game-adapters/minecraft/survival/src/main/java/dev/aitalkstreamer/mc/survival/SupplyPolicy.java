package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** One food acquisition episode. Movement and repeated task selection do not renew its budget. */
public final class SupplyPolicy {
    public enum Mode { COLLECT, FINISHED, FAILED }
    public record Decision(Mode mode, LocalTaskFailure.Reason reason) { }
    public record Facts(int nutrition, double anchorDistanceSquared) {
        public Facts {
            if (nutrition < 0 || !Double.isFinite(anchorDistanceSquared) || anchorDistanceSquared < 0)
                throw new IllegalArgumentException("Invalid supply facts");
        }
    }
    public record Limits(long totalMs, long noProgressMs, double radius) {
        public Limits {
            if (totalMs <= 0 || noProgressMs <= 0 || noProgressMs > totalMs || !Double.isFinite(radius) || radius <= 0)
                throw new IllegalArgumentException("Invalid supply limits");
        }
    }
    public static final Limits DEFAULT = new Limits(120_000, 45_000, 96);
    private final long started;
    private final int target;
    private final Limits limits;
    private long lastNow, progressAt;
    private int bestNutrition;
    private Decision decision = new Decision(Mode.COLLECT, null);

    public SupplyPolicy(long now, int target, Facts initial) { this(now,target,initial,DEFAULT); }
    public SupplyPolicy(long now, int target, Facts initial, Limits limits) {
        validateTarget(target);
        if (now < 0 || initial == null || limits == null) throw new IllegalArgumentException("Invalid supply start");
        started=lastNow=progressAt=now; this.target=target; this.limits=limits; bestNutrition=initial.nutrition;
    }
    public Decision observe(long now, Facts facts) {
        return observe(now, facts, true);
    }
    public Decision observe(long now, Facts facts, boolean childClean) {
        if (now < lastNow || facts == null) throw new IllegalArgumentException("Invalid supply observation");
        lastNow=now;
        if (decision.mode != Mode.COLLECT) return decision;
        // An overdue observation cannot retroactively turn a timed-out attempt into success.
        if (now-started >= limits.totalMs) return fail(SUPPLY_TIMEOUT);
        if (facts.anchorDistanceSquared > limits.radius*limits.radius) return fail(SUPPLY_RANGE_LIMIT);
        if (facts.nutrition >= target && childClean) return decision=new Decision(Mode.FINISHED,null);
        if (facts.nutrition > bestNutrition) { bestNutrition=facts.nutrition; progressAt=now; }
        if (now-progressAt >= limits.noProgressMs) return fail(SUPPLY_NO_PROGRESS);
        return decision;
    }
    private Decision fail(LocalTaskFailure.Reason reason) { return decision=new Decision(Mode.FAILED,reason); }
    public static int validateTarget(double units) {
        if (!Double.isFinite(units) || units < 1 || units > 256 || units != Math.rint(units))
            throw new LocalTaskFailure(SUPPLY_CONFIG_INVALID);
        return (int)units;
    }
    public static void validateSettings(int minimum, int target) {
        if (minimum==0 && target==0) return; // An existing explicit opt-out remains an opt-out.
        validateTarget(target);
        if (minimum<1 || minimum>target) throw new LocalTaskFailure(SUPPLY_CONFIG_INVALID);
    }
    /** Collection counts stock; protection of a stack from consumption does not make it absent. */
    public static boolean needsCollection(int nutrition, int minimum, int target, boolean collecting) {
        if (nutrition<0) throw new IllegalArgumentException("Invalid supply stock");
        validateSettings(minimum,target);
        if (minimum==0) return false;
        return nutrition<(collecting?target:minimum);
    }
    /** Total output targets, retaining already owned bread/wheat rather than asking for millions. */
    public static int breadTarget(double units) { int target=validateTarget(units); return (target+4)/5; }
    public static int wheatTarget(double units) { return Math.multiplyExact(breadTarget(units),3); }
}
