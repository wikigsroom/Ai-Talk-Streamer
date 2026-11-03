package dev.aitalkstreamer.mc.neoforge;

import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Reproduces a jump loop that the previous displacement clock counted forever. */
public final class TravelProgressFixture {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] args) {
        var progress = new NativeTravelProgress();
        var target = new Point(0,69,-1);
        long oldRenewed = 0, renewed = 0;
        double previousY = 68;
        for (int tick=0;tick<600;tick++) {
            double y = 68 + (tick%20<10 ? .7 : 0);
            if (Math.abs(y-previousY)>.4) { oldRenewed=tick*50; previousY=y; }
            if (progress.observe(target,69,.5,y,.5)) renewed=tick*50;
        }
        require(29950-oldRenewed<8000,"old jumping trace must reproduce false progress");
        require(29950-renewed>8000,"same trace must now hit the original no-progress deadline");
        require(progress.advances()<=1,"jumping cannot keep improving the same waypoint");
        progress.reset();
        target=new Point(8,64,0);
        require(!progress.observe(target,64,.5,64,.5),"first sample is only a baseline");
        int advances=0;
        for(int tick=1;tick<=60;tick++) if(progress.observe(target,64,.5+tick*.05,64,.5))advances++;
        require(advances>=10,"slow walking must accumulate meaningful distance");
        int before=progress.advances();
        for(int cycle=0;cycle<20;cycle++) {
            progress.observe(target,64,.5,64,.5);
            progress.observe(target,64,3.5,64,.5);
        }
        require(progress.advances()==before,"walking away and returning is not new progress");
        require(!progress.observe(new Point(-8,64,0),64,.5,64,.5),"route replacement does not renew the clock");
        require(!progress.observe(null,64,0,64,0),"missing waypoint refuses");
        require(!progress.observe(target,Double.NaN,0,64,0),"invalid surface refuses");
        progress.reset();
        require(progress.target()==null && progress.advances()==0,"new task clears all old evidence");
        target=new Point(0,68,0);
        progress.observe(target,68,.5,72,.5);
        require(progress.observe(target,68,.5,70,.5),"a genuine descent toward its landing counts");
        require(progress.observe(target,68,.5,68,.5),"reaching the landing counts");
        require(!progress.observe(target,68,.5,69,.5),"bouncing away does not count");
        System.out.println("TravelProgressFixture PASS: jump loop, slow walking, circling, route changes, descent and task reset");
    }
}
