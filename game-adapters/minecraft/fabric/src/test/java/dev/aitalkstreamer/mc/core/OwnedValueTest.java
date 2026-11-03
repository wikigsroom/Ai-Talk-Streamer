package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class OwnedValueTest {
    @Test void exactInstalledIdentityIsRequiredForOwnedMovement() {
        Object human=new Object(),first=new Object(),second=new Object();var current=new AtomicReference<>(human);
        var owned=new OwnedValue<>(current::get,current::set);
        assertFalse(owned.owns(human));owned.replace(first);assertTrue(owned.owns(first));
        owned.replace(second);assertFalse(owned.owns(first));assertTrue(owned.owns(second));
        owned.release();assertFalse(owned.owns(second));assertSame(human,current.get());
    }
    @Test void externalReplacementCannotImpersonateTheOwnedInputObject() {
        Object installed=new Object(),foreign=new Object();var current=new AtomicReference<>(new Object());
        var owned=new OwnedValue<>(current::get,current::set);owned.replace(installed);current.set(foreign);
        assertFalse(owned.owns(installed));assertFalse(owned.owns(foreign));owned.release();assertSame(foreign,current.get());
    }
    @Test void restoresTheExactPreviousInputObjectAfterSeveralReplacements() {
        Object human = new Object(); var current = new AtomicReference<>(human);
        var owned = new OwnedValue<>(current::get, current::set);
        owned.replace(new Object()); owned.replace(new Object()); owned.release();
        assertSame(human, current.get()); assertFalse(owned.owned());
    }
    @Test void externalReplacementIsPreservedOnRelease() {
        var current = new AtomicReference<>(new Object()); var owned = new OwnedValue<>(current::get, current::set);
        owned.replace(new Object()); Object foreign = new Object(); current.set(foreign); owned.release();
        assertSame(foreign, current.get()); assertFalse(owned.owned());
    }
    @Test void externalReplacementCannotBeOverwrittenByTheNextAutomationTick() {
        var current = new AtomicReference<>(new Object()); var owned = new OwnedValue<>(current::get, current::set);
        owned.replace(new Object()); Object foreign = new Object(); current.set(foreign);
        assertThrows(IllegalStateException.class, () -> owned.replace(new Object())); assertSame(foreign, current.get());
    }
    @Test void failedRestoreRemainsOwnedUntilSuccessfulRetry() {
        Object human = new Object(); var current = new AtomicReference<>(human); var fail = new AtomicBoolean();
        var owned = new OwnedValue<>(current::get, value -> { if (fail.get()) throw new IllegalStateException("fixture"); current.set(value); });
        owned.replace(new Object()); fail.set(true); assertThrows(IllegalStateException.class, owned::release); assertTrue(owned.owned());
        fail.set(false); owned.release(); assertSame(human, current.get());
    }
    @Test void setterThatMutatesThenThrowsStillHasARecoverableOriginal() {
        Object human = new Object(); var current = new AtomicReference<>(human); var fail = new AtomicBoolean(true);
        var owned = new OwnedValue<>(current::get, value -> { current.set(value); if (fail.get()) throw new IllegalStateException("fixture"); });
        assertThrows(IllegalStateException.class, () -> owned.replace(new Object())); fail.set(false); owned.release(); assertSame(human, current.get());
    }
    @Test void releaseWithoutOwnershipNeverWrites() {
        var owned = new OwnedValue<>(Object::new, value -> fail("unowned write")); owned.release(); assertFalse(owned.owned());
    }
}
