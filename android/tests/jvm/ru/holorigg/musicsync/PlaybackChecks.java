package ru.holorigg.musicsync;

import android.content.*;
import android.net.Uri;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import org.robolectric.*;
import org.robolectric.android.controller.ServiceController;
import org.robolectric.annotation.*;
import org.robolectric.shadows.ShadowMediaPlayer;
import java.util.*;
import java.io.IOException;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

/** Playback behavior checks backed only by Robolectric's synthetic media player. */
@RunWith(RobolectricTestRunner.class)
@Config(sdk=35)
public class PlaybackChecks {
    private Context context;
    private Store fixture;
    private ServiceController<PlaybackService> controller;
    private PlaybackService service;
    private final List<String> ids=Arrays.asList("1","2","3");

    @Before public void before()throws Exception{
        context=RuntimeEnvironment.getApplication();
        context.getSharedPreferences("settings",0).edit().clear().commit();
        context.deleteDatabase("music.db");
        PlaybackService.configure(context);
        fixture=new Store(context);
        Map<String,JSONObject> metadata=new HashMap<>();
        for(String id:ids){
            JSONObject track=new JSONObject().put("id",id).put("title","Fixture "+id).put("durationMs",20000)
                .put("available",true).put("artists",new JSONArray().put(new JSONObject().put("name","Synthetic Artist")));
            metadata.put(id,track);
        }
        fixture.catalog(ids,metadata);
        for(String id:ids){
            ContentValues row=new ContentValues();row.put("status","downloaded");row.put("uri","content://fixture/tracks/"+id);fixture.update(id,row);
            ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(context,Uri.parse("content://fixture/tracks/"+id)),new ShadowMediaPlayer.MediaInfo(20000,5));
        }
        controller=Robolectric.buildService(PlaybackService.class).create();service=controller.get();
    }

    @After public void after(){
        if(controller!=null)controller.destroy();
        if(fixture!=null)fixture.close();
        PlaybackService.currentId="";PlaybackService.currentTrack=new JSONObject();PlaybackService.playing=false;PlaybackService.loading=false;PlaybackService.prepared=false;
        PlaybackService.configure(context);
    }

    private void idle(long millis){Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(millis,TimeUnit.MILLISECONDS);}
    private void awaitPositionAtLeast(long target)throws Exception{for(int n=0;n<100&&PlaybackService.position()<target;n++)idle(10);assertTrue("seek should settle at the requested position",PlaybackService.position()>=target);}
    private void awaitPositionAtMost(long target)throws Exception{for(int n=0;n<100&&PlaybackService.position()>target;n++)idle(10);assertTrue("seek-to-zero should settle before the next Previous",PlaybackService.position()<=target);}
    private void start(String id){service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id",id).putStringArrayListExtra("queue",new ArrayList<>(ids)),0,1);idle(30);assertTrue("synthetic media should prepare",PlaybackService.prepared);}
    private void command(String action){service.onStartCommand(new Intent(context,PlaybackService.class).setAction(action),0,2);idle(30);}
    private boolean underlyingPlayerIsPlaying()throws Exception{java.lang.reflect.Field f=PlaybackService.class.getDeclaredField("player");f.setAccessible(true);android.media.MediaPlayer player=(android.media.MediaPlayer)f.get(service);return player!=null&&player.isPlaying();}
    private android.media.session.MediaSession.Callback callback(android.media.session.MediaSession session)throws Exception{java.lang.reflect.Field f=android.media.session.MediaSession.class.getDeclaredField("mCallback");f.setAccessible(true);Object handler=f.get(session);java.lang.reflect.Field c=handler.getClass().getDeclaredField("mCallback");c.setAccessible(true);return (android.media.session.MediaSession.Callback)c.get(handler);}

    @Test public void manualNextDoesNotWrapOrStopPlaybackAtEndWithoutRepeatAll()throws Exception{
        start("2");assertTrue(PlaybackService.canNext());
        command(PlaybackService.NEXT);assertEquals("3",PlaybackService.currentId);
        assertFalse("next is unavailable at the end in repeat-off mode",PlaybackService.canNext());
        command(PlaybackService.NEXT);assertEquals("manual Next at the end must leave the current song selected","3",PlaybackService.currentId);
        assertTrue("manual Next with no target must preserve service playback state",PlaybackService.playing);
        assertTrue("manual Next with no target must preserve the actual media player state",underlyingPlayerIsPlaying());
    }

    @Test public void manualNextIgnoresRepeatOneAndRepeatAllWraps(){
        // onCreate loaded OFF; cycle on the service to set ONE as the live mode.
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,1);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,2);
        assertEquals(PlaybackService.REPEAT_ONE,PlaybackService.repeatMode());
        start("2");command(PlaybackService.NEXT);
        assertEquals("manual Next advances even while Repeat One is active","3",PlaybackService.currentId);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,3); // OFF
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,4); // ALL
        assertEquals(PlaybackService.REPEAT_ALL,PlaybackService.repeatMode());
        start("3");assertTrue(PlaybackService.canNext());command(PlaybackService.NEXT);
        assertEquals("repeat-all wraps the ordered queue","1",PlaybackService.currentId);
    }

    @Test public void previousRestartsAfterThreeSecondsThenMovesBack()throws Exception{
        start("2");PlaybackService.seek(4000);awaitPositionAtLeast(4000);command(PlaybackService.PREVIOUS);awaitPositionAtMost(100);
        assertEquals("Previous after three seconds restarts the current track","2",PlaybackService.currentId);
        command(PlaybackService.PREVIOUS);assertEquals("1",PlaybackService.currentId);
    }

    @Test public void repeatOneCompletionRestartsCurrentTrack(){
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,1);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,2);
        assertEquals(PlaybackService.REPEAT_ONE,PlaybackService.repeatMode());
        for(String id:ids)ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(context,Uri.parse("content://fixture/tracks/"+id)),new ShadowMediaPlayer.MediaInfo(1000,5));
        start("2");idle(1100);
        assertEquals("Repeat One keeps the same queue item selected","2",PlaybackService.currentId);
        assertTrue("completion restarts the current item while Repeat One is active",PlaybackService.playing);
    }

    @Test public void shuffleAndRepeatModesPersistAcrossServiceRecreation(){
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("TOGGLE_SHUFFLE"),0,1);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,2);
        assertTrue(PlaybackService.isShuffle());assertEquals(PlaybackService.REPEAT_ALL,PlaybackService.repeatMode());
        controller.destroy();controller=Robolectric.buildService(PlaybackService.class).create();service=controller.get();
        assertTrue(PlaybackService.isShuffle());assertEquals(PlaybackService.REPEAT_ALL,PlaybackService.repeatMode());
    }

    @Test public void mediaSessionSkipCallbacksUsePreviousAndNextQueueRules()throws Exception{
        start("2");java.lang.reflect.Field f=PlaybackService.class.getDeclaredField("session");f.setAccessible(true);android.media.session.MediaSession session=(android.media.session.MediaSession)f.get(service);
        android.media.session.MediaController.TransportControls controls=session.getController().getTransportControls();android.media.session.MediaSession.Callback callback=callback(session);
        controls.skipToNext();assertEquals(android.media.session.PlaybackState.ACTION_SKIP_TO_NEXT,Shadows.shadowOf(controls).getLastPerformedAction());
        // Robolectric records TransportControls requests but does not route their binder calls to the
        // session callback, so invoke the registered callback to exercise the app's actual handler.
        callback.onSkipToNext();idle(30);assertEquals("3",PlaybackService.currentId);
        controls.skipToPrevious();assertEquals(android.media.session.PlaybackState.ACTION_SKIP_TO_PREVIOUS,Shadows.shadowOf(controls).getLastPerformedAction());
        callback.onSkipToPrevious();idle(30);assertEquals("2",PlaybackService.currentId);
        PlaybackService.seek(4000);awaitPositionAtLeast(4000);controls.skipToPrevious();callback.onSkipToPrevious();idle(30);awaitPositionAtMost(100);
        assertEquals("Previous from the media session restarts after three seconds","2",PlaybackService.currentId);
    }

    @Test public void pauseDuringPrepareIsRemembered(){
        ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(context,Uri.parse("content://fixture/tracks/1")),new ShadowMediaPlayer.MediaInfo(20000,500));
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","1").putStringArrayListExtra("queue",new ArrayList<>(ids)),0,1);
        command(PlaybackService.PAUSE);idle(600);
        assertTrue(PlaybackService.prepared);assertFalse("pause requested while loading must survive preparation",PlaybackService.playing);

    }

    @Test public void stalePrepareCallbackCannotReplaceTheCurrentTrack(){
        ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(context,Uri.parse("content://fixture/tracks/1")),new ShadowMediaPlayer.MediaInfo(20000,500));
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","1").putStringArrayListExtra("queue",new ArrayList<>(ids)),0,1);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","2").putStringArrayListExtra("queue",new ArrayList<>(ids)),0,2);
        idle(600);assertEquals("2",PlaybackService.currentId);assertTrue(PlaybackService.prepared);
    }

    @Test public void staleCompletionFromReleasedPlayerCannotAdvanceTheNewTrack(){
        ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(context,Uri.parse("content://fixture/tracks/1")),new ShadowMediaPlayer.MediaInfo(60,5));
        start("1");
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","2").putStringArrayListExtra("queue",new ArrayList<>(ids)),0,2);
        idle(150);assertEquals("completion from the released player must not skip the selected track","2",PlaybackService.currentId);assertTrue(PlaybackService.prepared);
    }

    @Test public void unavailableMiddleQueueRowIsSkippedToTheNextDownloadedTrack()throws Exception{
        JSONObject bad=new JSONObject().put("id","bad").put("title","Unavailable fixture").put("available",true);
        Map<String,JSONObject> rows=new HashMap<>();rows.put("1",new JSONObject().put("id","1").put("title","Fixture 1").put("available",true));rows.put("bad",bad);rows.put("2",new JSONObject().put("id","2").put("title","Fixture 2").put("available",true));
        fixture.catalog(Arrays.asList("1","bad","2"),rows);
        ContentValues pending=new ContentValues();pending.put("status","pending");fixture.update("bad",pending);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","1").putStringArrayListExtra("queue",new ArrayList<>(Arrays.asList("1","bad","2"))),0,1);idle(30);
        assertEquals("1",PlaybackService.currentId);
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.NEXT),0,2);idle(30);
        assertEquals("a row that stopped being downloaded is skipped","2",PlaybackService.currentId);assertTrue(PlaybackService.prepared);
    }

    @Test public void repeatAllWithEveryUriBrokenStopsAfterOneBoundedPass(){
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction("CYCLE_REPEAT"),0,1);
        assertEquals(PlaybackService.REPEAT_ALL,PlaybackService.repeatMode());
        for(String id:ids){
            Uri uri=Uri.parse("content://broken-fixture/tracks/"+id);
            ContentValues brokenUri=new ContentValues();brokenUri.put("uri",uri.toString());fixture.update(id,brokenUri);
            ShadowMediaPlayer.addException(org.robolectric.shadows.util.DataSource.toDataSource(context,uri),new IOException("synthetic broken source"));
        }
        service.onStartCommand(new Intent(context,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","1").putStringArrayListExtra("queue",new ArrayList<>(ids)),0,1);
        idle(50);
        assertFalse(PlaybackService.playing);assertFalse(PlaybackService.loading);assertFalse(PlaybackService.prepared);
        for(String id:ids){assertEquals("downloaded",fixture.row(id).optString("status"));assertEquals("content://broken-fixture/tracks/"+id,fixture.row(id).optString("uri"));}
    }

    @Test public void nextFromPausedPlaybackPreparesWithoutAutoplay(){
        start("1");command(PlaybackService.PAUSE);assertFalse(PlaybackService.playing);
        command(PlaybackService.NEXT);
        assertEquals("2",PlaybackService.currentId);assertTrue(PlaybackService.prepared);assertFalse(PlaybackService.playing);
        assertEquals("paused next should not leave an ongoing playback notification",0,service.notification().flags&android.app.Notification.FLAG_ONGOING_EVENT);
    }

    @Test public void automaticCompletionAdvancesThenStopsAtQueueEnd(){
        for(String id:ids)ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(context,Uri.parse("content://fixture/tracks/"+id)),new ShadowMediaPlayer.MediaInfo(1000,5));
        start("1");idle(1100);assertEquals("completion advances instead of stopping after the first track","2",PlaybackService.currentId);
        idle(1100);assertEquals("3",PlaybackService.currentId);idle(1100);
        assertEquals("3",PlaybackService.currentId);assertFalse(PlaybackService.playing);
    }
}
