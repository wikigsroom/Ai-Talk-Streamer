package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason;
import java.util.Objects;

/** One selected opponent, finite pursuit and finite escape. Finishing is not a kill receipt. */
public final class DefensePolicy {
    public enum Mode { FIGHT, RETREAT, FINISHED, FAILED }
    public record Decision(Mode mode, Reason reason) { }
    public record Facts(boolean targetPresent, boolean targetAlive, boolean ordinaryHostile,
                        double targetHealth, double targetDistanceSquared, double anchorDistanceSquared,
                        double health, double maxHealth, int food, int air, boolean underwater,
                        boolean burning, boolean lava, boolean dangerousTarget, boolean swordAvailable,
                        int armor, int threats, double closestThreatSquared) {
        public Facts {
            for (double value : new double[]{targetHealth,targetDistanceSquared,anchorDistanceSquared,
                    health,maxHealth,closestThreatSquared})
                if (!Double.isFinite(value) || value < 0) throw new IllegalArgumentException("Invalid defense facts");
            if (maxHealth <= 0 || health > maxHealth || food < 0 || food > 20 || air < 0
                    || armor < 0 || threats < 0) throw new IllegalArgumentException("Invalid defense facts");
        }
    }
    public record Limits(long totalMs, long noProgressMs, long escapeMs, double pursuitRadius,
                         double escapeRadius, double anchorRadius) {
        public Limits {
            if (totalMs <= 0 || noProgressMs <= 0 || escapeMs <= 0 || escapeMs > totalMs
                    || !Double.isFinite(pursuitRadius) || !Double.isFinite(escapeRadius) || !Double.isFinite(anchorRadius)
                    || pursuitRadius <= 0 || escapeRadius < pursuitRadius || anchorRadius <= escapeRadius)
                throw new IllegalArgumentException("Invalid defense limits");
        }
    }
    public static final Limits DEFAULTS = new Limits(30_000, 6_000, 10_000, 16, 16, 48);
    private final Limits limits;
    private final long started;
    private long lastTime, progressAt, escapingAt;
    private double bestHealth = Double.POSITIVE_INFINITY, bestDistance = Double.POSITIVE_INFINITY;
    private boolean seen, observed;
    private Decision decision = new Decision(Mode.FIGHT, null);
    public DefensePolicy(long now) { this(now, DEFAULTS); }
    public DefensePolicy(long now, Limits limits) {
        this.limits = Objects.requireNonNull(limits); started = lastTime = progressAt = now;
    }
    public Decision observe(long now, Facts facts) {
        Objects.requireNonNull(facts);
        if (now < lastTime) throw new IllegalArgumentException("Defense clock moved backwards");
        lastTime = now; observed = true;
        if (decision.mode == Mode.FINISHED || decision.mode == Mode.FAILED) return decision;
        boolean target = facts.targetPresent && facts.targetAlive;
        if ((!target || !facts.ordinaryHostile || facts.targetDistanceSquared > square(limits.escapeRadius))
                && (facts.threats == 0 || facts.closestThreatSquared > square(limits.escapeRadius)))
            return decision = new Decision(Mode.FINISHED, null);
        if (now - started >= limits.totalMs) return fail(Reason.DEFENSE_TIMEOUT);
        if (facts.anchorDistanceSquared > square(limits.anchorRadius)) return fail(Reason.DEFENSE_RANGE_LIMIT);
        if (decision.mode == Mode.RETREAT) {
            if (now - escapingAt >= limits.escapeMs) return fail(Reason.DEFENSE_ESCAPE_TIMEOUT);
            return decision;
        }
        boolean unsafe = !target || !facts.ordinaryHostile || facts.dangerousTarget || !facts.swordAvailable
                || facts.health <= 8 || facts.health <= facts.maxHealth * .35 || facts.food <= 6
                || facts.lava || facts.burning || facts.underwater && facts.air < 60
                || facts.threats > 1 + Math.min(20, facts.armor) / 8
                || facts.targetDistanceSquared > square(limits.pursuitRadius);
        if (unsafe) {
            escapingAt = now;
            return decision = new Decision(Mode.RETREAT, null);
        }
        if (!seen || facts.targetHealth < bestHealth || facts.targetDistanceSquared <= bestDistance - 1) {
            seen = true; progressAt = now;
            bestHealth = Math.min(bestHealth, facts.targetHealth);
            bestDistance = Math.min(bestDistance, facts.targetDistanceSquared);
        }
        if (now - progressAt >= limits.noProgressMs) return fail(Reason.DEFENSE_NO_PROGRESS);
        return decision;
    }
    boolean permitsAttack(boolean selectedTarget, boolean projectileReflection) {
        return observed && (decision.mode == Mode.FINISHED
                || decision.mode == Mode.FIGHT && selectedTarget
                || projectileReflection && decision.mode != Mode.FAILED);
    }
    private Decision fail(Reason reason) { return decision = new Decision(Mode.FAILED, reason); }
    private static double square(double value) { return value * value; }
}
