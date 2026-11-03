package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

class SurvivalAsyncTest {
    private final AtomicLong now=new AtomicLong(10000);
    private final ControlArbiter control=new ControlArbiter(now::get,()->{});
    private SurvivalAuthority.Session session;
    private final AtomicReference<Thread> workerThread=new AtomicReference<>();
    private final ExecutorService worker=Executors.newSingleThreadExecutor(action->{Thread thread=new Thread(action,"test-survival-calculation");workerThread.set(thread);return thread;});
    private final AtomicInteger effects=new AtomicInteger();
    @BeforeEach void setup() {
        control.world("world");control.attach("controller");control.release(control.epoch(),()->{});control.observe(1);control.beginAuto("controller","world",control.epoch(),true);
        control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),10000);open();
    }
    private void open() {var p=control.permit();session=SurvivalAuthority.open(new SurvivalAuthority.Context("task",p.controller(),p.lease(),p.world(),p.epoch()),new ArbiterBoundary(control,p,"task"));}
    private void effect() {SurvivalAuthority.write(effects::incrementAndGet);}
    private void submit(Runnable action) {SurvivalAuthority.run(session,()->SurvivalAsync.execute(worker,action));}
    private void barrier() throws Exception {worker.submit(()->{}).get(3,TimeUnit.SECONDS);}
    private void drain() {SurvivalAuthority.run(session,SurvivalAsync::drain);}
    @AfterEach void cleanup() throws InterruptedException {session.close(()->{},()->{});worker.shutdownNow();assertTrue(worker.awaitTermination(3,TimeUnit.SECONDS));}
    @Test void computeHasNoGamePermissionAndOnlyClientDrainAppliesTheResult() throws Exception {
        submit(()->{assertFalse(SurvivalAuthority.inScope());assertThrows(SurvivalAuthority.Denied.class,this::effect);SurvivalAsync.commit(this::effect);});
        barrier();assertEquals(0,effects.get());drain();assertEquals(1,effects.get());drain();assertEquals(1,effects.get());
    }
    @Test void submissionRequiresAnAcceptedRoot() {assertThrows(SurvivalAuthority.Denied.class,()->SurvivalAsync.execute(worker,()->fail("unowned calculation")));}
    @Test void resultWithoutItsCapturedWorkerOriginIsRejected() {assertEquals("GAME_PATH_RESULT_WITHOUT_ORIGIN",assertThrows(IllegalStateException.class,()->SurvivalAsync.commit(this::effect)).getMessage());}
    @Test void queuedOldResultCannotApplyInTheNextRoot() throws Exception {
        submit(()->SurvivalAsync.commit(this::effect));barrier();session.close(()->{},()->{});open();drain();assertEquals(0,effects.get());
    }
    @Test void resultFinishingAfterCloseCannotAdoptTheNextRoot() throws Exception {
        CountDownLatch started=new CountDownLatch(1),resume=new CountDownLatch(1);
        submit(()->{started.countDown();try{assertTrue(resume.await(3,TimeUnit.SECONDS));}catch(InterruptedException e){throw new AssertionError(e);}SurvivalAsync.commit(this::effect);});
        assertTrue(started.await(3,TimeUnit.SECONDS));session.close(()->{},()->{});open();resume.countDown();barrier();drain();assertEquals(0,effects.get());
    }
    @Test void aJobRevokedBeforeWorkerStartDoesNotEvenCompute() throws Exception {
        List<Runnable> jobs=new ArrayList<>();AtomicInteger calls=new AtomicInteger();
        SurvivalAuthority.run(session,()->SurvivalAsync.execute(jobs::add,calls::incrementAndGet));session.close(()->{},()->{});worker.submit(jobs.getFirst()).get(3,TimeUnit.SECONDS);assertEquals(0,calls.get());
    }
    @Test void leaseExpiryBeforeCommitDropsTheResult() throws Exception {
        submit(()->{now.set(21000);SurvivalAsync.commit(this::effect);});barrier();assertFalse(session.current());session.close(()->{},()->{});
        assertEquals(0,effects.get());
    }
    @Test void workerFailureIsRetainedForClientFailureHandling() throws Exception {
        submit(()->{throw new IllegalArgumentException("fixture calculation");});barrier();assertFalse(session.current());
        assertInstanceOf(IllegalArgumentException.class,assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session)).getCause());
    }
    @Test void inlineExecutorCannotRunCalculationOnTheClientThread() {
        SurvivalAuthority.run(session,()->SurvivalAsync.execute(Runnable::run,()->fail("inline calculation")));
        assertFalse(session.current());assertEquals("GAME_ASYNC_EXECUTOR_THREAD",assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session)).getCause().getMessage());
    }
    @Test void rejectedSubmissionsReleaseTheirBudgetAndAValidRetryCanComplete() throws Exception {
        SurvivalAuthority.run(session,()->{for(int i=0;i<12;i++)assertThrows(RejectedExecutionException.class,()->SurvivalAsync.execute(job->{throw new RejectedExecutionException();},()->{}));});
        submit(()->SurvivalAsync.commit(this::effect));barrier();drain();assertEquals(1,effects.get());
    }
    @Test void duplicateExecutorDeliveryComputesAndCommitsOnlyOnce() throws Exception {
        List<Runnable> jobs=new ArrayList<>();AtomicInteger calls=new AtomicInteger();
        SurvivalAuthority.run(session,()->SurvivalAsync.execute(jobs::add,()->{calls.incrementAndGet();SurvivalAsync.commit(this::effect);}));
        worker.submit(jobs.getFirst()).get(3,TimeUnit.SECONDS);worker.submit(jobs.getFirst()).get(3,TimeUnit.SECONDS);drain();assertEquals(1,calls.get());assertEquals(1,effects.get());
    }
    @Test void resultOverflowRevokesTheRootAndNeverAppliesItsPartialQueue() throws Exception {
        submit(()->{for(int i=0;i<65;i++)SurvivalAsync.commit(this::effect);});barrier();assertFalse(session.current());
        assertEquals("GAME_ASYNC_RESULT_LIMIT",assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session)).getCause().getMessage());
        session.close(()->{},()->{});open();drain();assertEquals(0,effects.get());
    }
    @Test void inFlightBudgetRejectsTheNinthJobAndCloseDropsAllEight() throws Exception {
        List<Runnable> jobs=new ArrayList<>();AtomicInteger calls=new AtomicInteger();
        SurvivalAuthority.run(session,()->{for(int i=0;i<8;i++)SurvivalAsync.execute(jobs::add,calls::incrementAndGet);
            assertEquals("GAME_ASYNC_JOB_LIMIT",assertThrows(IllegalStateException.class,()->SurvivalAsync.execute(jobs::add,calls::incrementAndGet)).getMessage());});
        session.close(()->{},()->{});for(var job:jobs)worker.submit(job).get(3,TimeUnit.SECONDS);assertEquals(0,calls.get());
    }
    @Test void closingRootsRemovesTheAsyncRegistryWithoutWaitingForAnotherEvent() throws ReflectiveOperationException {
        var field=SurvivalAsync.class.getDeclaredField("STATES");field.setAccessible(true);
        for(int i=0;i<100;i++){SurvivalAuthority.run(session,SurvivalAsync::prepare);session.close(()->{},()->{});assertTrue(((Map<?,?>)field.get(null)).isEmpty());if(i<99)open();}
    }
    @Test void workerDoesNotHoldTheResultMonitorWhileWaitingForNativeControl() throws Exception {
        SurvivalAuthority.run(session,()->{
            synchronized(control) {
                SurvivalAsync.execute(worker,()->SurvivalAsync.commit(this::effect));
                long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
                while((workerThread.get()==null||workerThread.get().getState()!=Thread.State.BLOCKED)&&System.nanoTime()<deadline)Thread.onSpinWait();
                assertNotNull(workerThread.get());assertEquals(Thread.State.BLOCKED,workerThread.get().getState());
                var info=java.lang.management.ManagementFactory.getThreadMXBean().getThreadInfo(new long[]{workerThread.get().threadId()},true,true)[0];
                assertEquals(ControlArbiter.class.getName(),info.getLockInfo().getClassName());
                assertFalse(Arrays.stream(info.getLockedMonitors()).anyMatch(m->m.getClassName().equals("dev.aitalkstreamer.mc.survival.SurvivalAsync$State")));
            }
        });barrier();drain();assertEquals(1,effects.get());
    }
    @Test void invalidationDropsAlreadyQueuedBranchResultsInTheSameRoot()throws Exception {
        submit(()->SurvivalAsync.commit(this::effect));barrier();SurvivalAuthority.run(session,SurvivalAsync::invalidate);drain();assertEquals(0,effects.get());assertTrue(session.current());
    }
    @Test void invalidationDropsAWorkerWhichFinishesAfterTheBranchChanged()throws Exception {
        var started=new CountDownLatch(1);var resume=new CountDownLatch(1);
        submit(()->{started.countDown();try{assertTrue(resume.await(3,TimeUnit.SECONDS));}catch(InterruptedException e){throw new AssertionError(e);}SurvivalAsync.commit(this::effect);});
        assertTrue(started.await(3,TimeUnit.SECONDS));SurvivalAuthority.run(session,SurvivalAsync::invalidate);resume.countDown();barrier();drain();assertEquals(0,effects.get());assertTrue(session.current());
    }
    @Test void aCancelledGenerationDoesNotStartAQueuedCalculation()throws Exception {
        var jobs=new ArrayList<Runnable>();var calls=new AtomicInteger();
        SurvivalAuthority.run(session,()->SurvivalAsync.execute(jobs::add,calls::incrementAndGet));SurvivalAuthority.run(session,SurvivalAsync::invalidate);
        worker.submit(jobs.getFirst()).get(3,TimeUnit.SECONDS);assertEquals(0,calls.get());assertTrue(session.current());
    }
    @Test void obsoleteWorkerFailureCannotRevokeTheReplacementBranch()throws Exception {
        var started=new CountDownLatch(1);var resume=new CountDownLatch(1);
        submit(()->{started.countDown();try{assertTrue(resume.await(3,TimeUnit.SECONDS));}catch(InterruptedException e){throw new AssertionError(e);}throw new IllegalStateException("obsolete calculation");});
        assertTrue(started.await(3,TimeUnit.SECONDS));SurvivalAuthority.run(session,SurvivalAsync::invalidate);resume.countDown();barrier();drain();assertTrue(session.current());
    }
    @Test void currentGenerationFailureStillRevokesTheRoot()throws Exception {
        SurvivalAuthority.run(session,SurvivalAsync::invalidate);submit(()->{throw new IllegalStateException("current calculation");});barrier();assertFalse(session.current());
        assertEquals("current calculation",assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session)).getCause().getMessage());
    }
    @Test void invalidationDoesNotResetTheEightInFlightJobBudget()throws Exception {
        var jobs=new ArrayList<Runnable>();SurvivalAuthority.run(session,()->{for(int i=0;i<8;i++)SurvivalAsync.execute(jobs::add,()->{});SurvivalAsync.invalidate();
            assertEquals("GAME_ASYNC_JOB_LIMIT",assertThrows(IllegalStateException.class,()->SurvivalAsync.execute(jobs::add,()->{})).getMessage());});
        for(var job:jobs)worker.submit(job).get(3,TimeUnit.SECONDS);submit(()->SurvivalAsync.commit(this::effect));barrier();drain();assertEquals(1,effects.get());
    }
    @Test void replacementResultsCanCommitUnderTheOriginalPermit()throws Exception {
        var context=session.context();submit(()->SurvivalAsync.commit(this::effect));barrier();SurvivalAuthority.run(session,SurvivalAsync::invalidate);
        submit(()->SurvivalAsync.commit(this::effect));barrier();drain();assertEquals(1,effects.get());assertSame(context,session.context());
    }
    @Test void clearedQueuesDoNotRetainTheOldSixtyFourResultCapacity()throws Exception {
        submit(()->{for(int i=0;i<64;i++)SurvivalAsync.commit(this::effect);});barrier();SurvivalAuthority.run(session,SurvivalAsync::invalidate);
        submit(()->{for(int i=0;i<64;i++)SurvivalAsync.commit(this::effect);});barrier();drain();assertEquals(64,effects.get());assertTrue(session.current());
    }
    @Test void repeatedBranchChangesCannotBringOldResultsBack()throws Exception {
        for(int i=0;i<40;i++){submit(()->SurvivalAsync.commit(this::effect));barrier();SurvivalAuthority.run(session,SurvivalAsync::invalidate);}
        drain();assertEquals(0,effects.get());submit(()->SurvivalAsync.commit(this::effect));barrier();drain();assertEquals(1,effects.get());
    }
    @Test void invalidationCannotAcquireAuthorityOrHideARecordedFailure()throws Exception {
        assertThrows(SurvivalAuthority.Denied.class,SurvivalAsync::invalidate);
        submit(()->{throw new IllegalStateException("recorded failure");});barrier();assertThrows(RuntimeException.class,()->SurvivalAuthority.run(session,SurvivalAsync::invalidate));
        assertEquals("recorded failure",assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session)).getCause().getMessage());
    }
    @Test void replacementWaitObservesTheOldWorkerUntilItActuallyExits()throws Exception {
        var started=new CountDownLatch(1);var resume=new CountDownLatch(1);
        submit(()->{started.countDown();try{assertTrue(resume.await(3,TimeUnit.SECONDS));}catch(InterruptedException e){throw new AssertionError(e);}});
        assertTrue(started.await(3,TimeUnit.SECONDS));SurvivalAuthority.run(session,()->{SurvivalAsync.invalidate();assertFalse(SurvivalAsync.quiescent());});
        resume.countDown();barrier();SurvivalAuthority.run(session,()->assertTrue(SurvivalAsync.quiescent()));
    }
    @Test void anUnstartedCancelledJobStillOwnsItsConcurrentSlotUntilDelivered()throws Exception {
        var jobs=new ArrayList<Runnable>();SurvivalAuthority.run(session,()->{SurvivalAsync.execute(jobs::add,()->fail("cancelled work"));SurvivalAsync.invalidate();assertFalse(SurvivalAsync.quiescent());});
        worker.submit(jobs.getFirst()).get(3,TimeUnit.SECONDS);SurvivalAuthority.run(session,()->assertTrue(SurvivalAsync.quiescent()));
    }
    @Test void quiescenceRequiresBothCompletedWorkAndDrainedResults()throws Exception {
        submit(()->SurvivalAsync.commit(this::effect));barrier();SurvivalAuthority.run(session,()->assertFalse(SurvivalAsync.quiescent()));
        drain();SurvivalAuthority.run(session,()->assertTrue(SurvivalAsync.quiescent()));assertEquals(1,effects.get());
        assertThrows(SurvivalAuthority.Denied.class,SurvivalAsync::quiescent);
    }
    @Test void retirementDropsOldResultsBeforeSynchronousCleanupCanDrainThem()throws Exception {
        submit(()->SurvivalAsync.commit(this::effect));barrier();
        SurvivalAuthority.run(session,()->{SurvivalAsync.invalidate();SurvivalAsync.drain();assertEquals(0,effects.get());SurvivalAsync.invalidate();});
        submit(()->SurvivalAsync.commit(this::effect));barrier();drain();assertEquals(1,effects.get());
    }
    @Test void aCalculationSubmittedDuringCleanupCannotOutliveTheSecondRetirementFence()throws Exception {
        SurvivalAuthority.run(session,SurvivalAsync::invalidate);submit(()->SurvivalAsync.commit(this::effect));barrier();
        SurvivalAuthority.run(session,()->{SurvivalAsync.invalidate();assertTrue(SurvivalAsync.quiescent());});drain();assertEquals(0,effects.get());
        submit(()->SurvivalAsync.commit(this::effect));barrier();drain();assertEquals(1,effects.get());assertTrue(session.current());
    }
    @Test void aCurrentCleanupCalculationFailureCannotBeHiddenByTheSecondFence()throws Exception {
        SurvivalAuthority.run(session,SurvivalAsync::invalidate);submit(()->{throw new IllegalStateException("cleanup calculation failure");});barrier();
        assertThrows(RuntimeException.class,()->SurvivalAuthority.run(session,SurvivalAsync::invalidate));
        assertEquals("cleanup calculation failure",assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session)).getCause().getMessage());
    }
}
