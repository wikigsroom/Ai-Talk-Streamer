package dev.aitalkstreamer.mc.core;

import java.util.Objects;

/** Client-thread generation fence: delayed cleanup cannot release a later task's inputs. */
public final class InputLeaseFence {
    private final Runnable release;
    private long generation;
    public InputLeaseFence(Runnable release) { this.release = Objects.requireNonNull(release); }
    public Ticket ticket() { return new Ticket(generation); }
    public void releaseAll() {
        release.run();
        // A failed restoration retains this generation for an explicit retry.
        generation++;
    }
    public final class Ticket {
        private final long accepted;
        private Ticket(long accepted) { this.accepted = accepted; }
        public void check() {
            if (accepted != generation) throw new IllegalStateException("GAME_INPUT_GENERATION_CHANGED");
        }
        public void release() { if (accepted == generation) releaseAll(); }
    }
}
