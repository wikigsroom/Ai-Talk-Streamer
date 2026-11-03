package dev.aitalkstreamer.mc.neoforge;

/** A pursuit must gain full input without granting sprint across turns, hazards or lost footing. */
public final class EscapeMotionFixture {
    private static int checks;
    private static void check(boolean value) { checks++; if(!value)throw new AssertionError("ESCAPE_MOTION_"+checks); }
    public static void main(String[] args) {
        check(NativeEscapeMotion.throttle(true,true,4)==1);
        check(NativeEscapeMotion.throttle(false,true,4)==.5f);
        check(NativeEscapeMotion.throttle(true,true,.1)==.2f);
        check(NativeEscapeMotion.sprint(true,true,false,false,false,false,7,1,0,0));
        check(NativeEscapeMotion.sprint(true,true,false,false,false,false,20,1,25,.0625));
        check(!NativeEscapeMotion.sprint(false,true,false,false,false,false,20,1,0,0));
        check(!NativeEscapeMotion.sprint(true,false,false,false,false,false,20,1,0,0));
        check(!NativeEscapeMotion.sprint(true,true,true,false,false,false,20,1,0,0));
        check(!NativeEscapeMotion.sprint(true,true,false,true,false,false,20,1,0,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,true,false,20,1,0,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,true,20,1,0,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,false,6,1,0,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,false,20,.5f,0,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,false,20,1,26,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,false,20,1,0,1));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,false,20,1,Float.NaN,0));
        check(!NativeEscapeMotion.sprint(true,true,false,false,false,false,20,1,0,Double.NaN));
        System.out.println("PASS "+checks+" escape input boundaries; no world or movement writes");
    }
}
