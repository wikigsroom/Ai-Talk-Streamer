package dev.aitalkstreamer.mc.neoforge;

/** Task ownership and landing boundaries only; not a physical Minecraft simulation. */
public final class RouteRecoveryBudgetFixture {
    private static int checks;
    private static void check(boolean value) { checks++;if(!value)throw new AssertionError("RECOVERY_BUDGET_"+checks); }
    public static void main(String[] args) {
        var budget=new NativeRouteRecovery();var world=new Object();var player=new Object();var connection=new Object();
        budget.bind("original",world,player,connection);
        for(int i=0;i<4;i++)check(budget.admitRoute());
        check(!budget.admitRoute());
        budget.bind("original",world,player,connection);
        check(!budget.admitRoute());check(budget.attempts()==4);
        for(int i=0;i<20;i++)check(budget.landing(false,false,false)==NativeEscapeLanding.State.WAITING);
        check(budget.landing(true,false,false)==NativeEscapeLanding.State.READY);
        check(!budget.waiting());check(budget.landingTicks()==20);
        // Restarting a survival child cannot refill the original task's allowance.
        budget.bind("original",world,player,connection);
        for(int i=0;i<20;i++)check(budget.landing(false,false,false)==NativeEscapeLanding.State.WAITING);
        check(budget.landing(false,false,false)==NativeEscapeLanding.State.TIMED_OUT);
        check(budget.landingTicks()==40);check(budget.episodes()==2);
        budget.bind("original",world,player,connection);
        check(budget.landing(false,false,false)==NativeEscapeLanding.State.TIMED_OUT);
        check(budget.landingTicks()==40);
        budget.bind("next",world,player,connection);
        check(budget.admitRoute());check(budget.landingTicks()==0);
        for(int i=0;i<20;i++)check(budget.landing(false,false,false)==NativeEscapeLanding.State.WAITING);
        check(budget.landing(false,false,false)==NativeEscapeLanding.State.TIMED_OUT);
        check(budget.landing(true,false,false)==NativeEscapeLanding.State.READY);
        check(budget.landing(false,true,false)==NativeEscapeLanding.State.UNSUPPORTED);
        check(budget.landing(false,false,true)==NativeEscapeLanding.State.UNSUPPORTED);
        for(Object[] changed:new Object[][]{{new Object(),player,connection},{world,new Object(),connection},{world,player,new Object()}}) {
            budget.bind("next",changed[0],changed[1],changed[2]);
            check(budget.attempts()==0 && budget.landingTicks()==0);check(budget.admitRoute());
        }
        System.out.println("PASS "+checks+" original-task recovery and landing boundary checks; no game acceptance");
    }
}
