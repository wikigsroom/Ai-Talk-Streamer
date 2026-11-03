package dev.aitalkstreamer.mc.neoforge;

/** Frame lifecycle boundaries; does not start Minecraft or verify the Windows desktop. */
public final class NativeWorldFramesFixture {
    private static int checks;
    private static void check(boolean value, String why) { checks++; if (!value) throw new AssertionError(why); }
    public static void main(String[] args) {
        NativeWorldFrames f = new NativeWorldFrames();
        Object w = new Object(), p = new Object(), c = new Object();
        check(!f.ready(w,p,c), "tick data alone is not a rendered frame");
        for (int i=1;i<=3;i++) {
            f.rendered(w,p,c,true);
            check(f.frames()==i && f.ready(w,p,c)==(i==3), "three eligible completed frames required");
        }
        f.rendered(w,p,c,false);
        check(f.ready(w,p,c), "normal pause menu retains same-world first-frame receipts");
        for (int i=0;i<100;i++) f.rendered(w,p,c,true);
        check(f.frames()==3, "bounded counter");
        long generation=f.generation(); p=new Object();
        check(!f.ready(w,p,c) && f.generation()==generation+1, "replacement player invalidates receipts");
        f.rendered(w,p,c,true); f.rendered(w,p,c,false);
        check(f.frames()==0 && !f.ready(w,p,c), "loading overlay or incomplete frame breaks initial run");
        for (int i=0;i<3;i++) f.rendered(w,p,c,true);
        c=new Object(); check(!f.ready(w,p,c), "new connection invalidates receipts");
        for (int i=0;i<3;i++) f.rendered(w,p,c,true);
        w=new Object(); check(!f.ready(w,p,c), "world switch invalidates receipts");
        for (int missing=0;missing<3;missing++) {
            Object a=missing==0?null:w,b=missing==1?null:p,d=missing==2?null:c;
            for (int i=0;i<5;i++) f.rendered(a,b,d,true);
            check(!f.ready(a,b,d) && f.frames()==0, "partial world cannot establish rendering readiness");
        }
        check(!f.ready(null,null,null), "title screen invalidates world");
        for (int i=0;i<3;i++) f.rendered(w,p,c,true);
        check(f.ready(w,p,c), "ordinary reload needs fresh complete frames");
        System.out.println("PASS: "+checks+" frame lifecycle checks; JVM_FIXTURE_NOT_DESKTOP_PRESENTATION");
    }
}
