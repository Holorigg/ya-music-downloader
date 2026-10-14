package ru.holorigg.musicsync;

import android.content.*;
import android.content.res.Configuration;
import android.view.*;
import android.widget.*;
import android.app.Notification;
import android.app.NotificationManager;
import androidx.core.view.ViewCompat;
import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.google.android.material.materialswitch.MaterialSwitch;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import org.robolectric.*;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.*;
import org.robolectric.shadows.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk=35,qualifiers="w411dp-h891dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.LEGACY)
public class UiChecks {
    private Store store;private ActivityController<MainActivity> controller;
    @Before public void before(){Context c=RuntimeEnvironment.getApplication();c.getSharedPreferences("settings",0).edit().clear().commit();c.deleteDatabase("music.db");store=new Store(c);SyncEngine.running.set(false);SyncEngine.stop.set(false);Store.revision.incrementAndGet();PlaybackService.currentId="";}
    @After public void after(){if(controller!=null)controller.pause().stop().destroy();store.close();SyncEngine.running.set(false);}
    private MainActivity open(){controller=Robolectric.buildActivity(MainActivity.class).setup();MainActivity a=controller.get();measure(a);return a;}
    private void measure(MainActivity a){View decor=a.getWindow().getDecorView();decor.measure(View.MeasureSpec.makeMeasureSpec(411,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(891,View.MeasureSpec.EXACTLY));decor.layout(0,0,411,891);}
    private void awaitRows()throws Exception{for(int n=0;n<40;n++){Thread.sleep(25);Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();}measure(controller.get());}
    private void seed()throws Exception{Map<String,JSONObject> metadata=new HashMap<>();for(int n=1;n<=3;n++){JSONObject track=new JSONObject().put("id",String.valueOf(n)).put("title",n==1?"Трек 01":n==2?"Очень длинное название песни для проверки вёрстки":"Осень").put("available",true).put("durationMs",135000).put("artists",new JSONArray().put(new JSONObject().put("name",n==1?"Demo Artist":"Исполнитель")));metadata.put(String.valueOf(n),track);}store.catalog(Arrays.asList("1","2","3"),metadata);ContentValues values=new ContentValues();values.put("status","downloaded");values.put("uri","content://music/tracks/1");store.update("1",values);store.fail("3","Сеть недоступна");}
    @Test public void materialScreensKeepV1Settings()throws Exception{
        store.prefs.edit().putString("auth","encrypted-existing-auth").putString("tree","content://com.android.externalstorage.documents/tree/primary%3AMusic").putString("account_name","Демо").putInt("hours",24).putBoolean("lyrics",false).commit();seed();MainActivity a=open();awaitRows();
        BottomNavigationView nav=a.findViewById(R.id.navigation);assertEquals(3,nav.getMenu().size());assertEquals(R.id.nav_library,nav.getSelectedItemId());
        assertNotNull(a.findViewById(R.id.library_list));assertEquals(3,((androidx.recyclerview.widget.RecyclerView)a.findViewById(R.id.library_list)).getAdapter().getItemCount());
        nav.setSelectedItemId(R.id.nav_settings);measure(a);assertNotNull(a.findViewById(R.id.theme_button));MaterialSwitch auto=a.findViewById(R.id.auto_switch);assertFalse(auto.isChecked());assertFalse(((MaterialSwitch)a.findViewById(R.id.lyrics_switch)).isChecked());
        auto.setChecked(true);assertTrue(store.prefs.getBoolean("auto",false));assertNotNull(a.getSystemService(android.app.job.JobScheduler.class).getPendingJob(Scheduler.ID));auto.setChecked(false);assertNull(a.getSystemService(android.app.job.JobScheduler.class).getPendingJob(Scheduler.ID));
        nav.setSelectedItemId(R.id.nav_account);measure(a);assertNotNull(a.findViewById(R.id.account_login));assertEquals("encrypted-existing-auth",store.prefs.getString("auth",""));assertEquals(24,store.prefs.getInt("hours",0));
    }
    @Test public void searchFiltersWithoutNetworkOrDuplicates()throws Exception{seed();MainActivity a=open();awaitRows();EditText search=a.findViewById(R.id.search);search.setText("Demo Artist");assertEquals(1,((androidx.recyclerview.widget.RecyclerView)a.findViewById(R.id.library_list)).getAdapter().getItemCount());search.setText("несуществующий трек");assertEquals(View.VISIBLE,a.findViewById(R.id.library_empty).getVisibility());search.setText("");assertEquals(3,((androidx.recyclerview.widget.RecyclerView)a.findViewById(R.id.library_list)).getAdapter().getItemCount());}
    @Test @Config(qualifiers="w411dp-h891dp-night-mdpi") public void darkThemeInflatesEveryTab(){MainActivity a=open();assertFalse(a.getResources().getBoolean(R.bool.light_system_bars));BottomNavigationView nav=a.findViewById(R.id.navigation);nav.setSelectedItemId(R.id.nav_settings);measure(a);nav.setSelectedItemId(R.id.nav_account);measure(a);assertNotNull(a.findViewById(R.id.account_login));}
    @Test public void autoCannotStartWithoutAccountAndFolder(){MainActivity a=open();((BottomNavigationView)a.findViewById(R.id.navigation)).setSelectedItemId(R.id.nav_settings);MaterialSwitch auto=a.findViewById(R.id.auto_switch);auto.setChecked(true);assertFalse(auto.isChecked());assertFalse(store.prefs.getBoolean("auto",false));}
    @Test @Config(sdk=26) public void android8CanOpenEveryMaterialScreen(){MainActivity a=open();BottomNavigationView nav=a.findViewById(R.id.navigation);nav.setSelectedItemId(R.id.nav_settings);measure(a);assertNotNull(a.findViewById(R.id.auto_switch));nav.setSelectedItemId(R.id.nav_account);measure(a);assertNotNull(a.findViewById(R.id.account_login));}
    @Test public void progressChangesBetweenCatalogAndDownload(){MainActivity a=open();SyncEngine.begin(false);Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);assertEquals(View.VISIBLE,a.findViewById(R.id.sync_panel).getVisibility());SyncEngine.total=20;SyncEngine.completed=3;SyncEngine.phase="download";Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);SyncEngine.total=0;SyncEngine.phase="catalog";Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);SyncEngine.running.set(false);Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);assertEquals(View.GONE,a.findViewById(R.id.sync_panel).getVisibility());}
    @Test public void notificationsHaveProgressStopAndLoginAction(){Context c=RuntimeEnvironment.getApplication();SyncNotifications.channels(c);SyncEngine.phase="download";SyncEngine.currentTrack="Название песни";SyncEngine.total=10;SyncEngine.completed=4;Notification n=SyncNotifications.ongoing(c);assertEquals("Скачивание музыки",n.extras.getString(Notification.EXTRA_TITLE));assertEquals(10,n.extras.getInt(Notification.EXTRA_PROGRESS_MAX));assertEquals(4,n.extras.getInt(Notification.EXTRA_PROGRESS));assertEquals(1,n.actions.length);Intent stop=Shadows.shadowOf(n.actions[0].actionIntent).getSavedIntent();assertEquals(SyncControl.STOP,stop.getAction());assertEquals(SyncControl.class.getName(),stop.getComponent().getClassName());
        SyncNotifications.finish(c,store,"login",false);Notification result=Shadows.shadowOf(c.getSystemService(NotificationManager.class)).getNotification(SyncNotifications.RESULT);assertNotNull(result);assertEquals(2,Shadows.shadowOf(result.contentIntent).getSavedIntent().getIntExtra("tab",-1));
        c.getSystemService(NotificationManager.class).cancel(SyncNotifications.RESULT);store.prefs.edit().putInt("last_added",0).putInt("last_missing",0).commit();SyncNotifications.finish(c,store,"done",true);assertNull(Shadows.shadowOf(c.getSystemService(NotificationManager.class)).getNotification(SyncNotifications.RESULT));
    }
    @Test public void musicNotificationHasSystemMediaSessionAndControls(){android.app.Service s=Robolectric.buildService(PlaybackService.class).create().get();PlaybackService.currentId="1";PlaybackService.currentTrack=new JSONObject();Notification n=((PlaybackService)s).notification();assertEquals(Notification.CATEGORY_TRANSPORT,n.category);assertNotNull(n.extras.getParcelable(Notification.EXTRA_MEDIA_SESSION));assertEquals(2,n.actions.length);assertEquals(PlaybackService.PLAY,Shadows.shadowOf(n.actions[0].actionIntent).getSavedIntent().getAction());s.onDestroy();}
    @Test public void playbackPreparePauseSeekAndUnplug()throws Exception{
        seed();Context c=RuntimeEnvironment.getApplication();android.net.Uri uri=android.net.Uri.parse("content://music/tracks/1");ShadowMediaPlayer.addMediaInfo(org.robolectric.shadows.util.DataSource.toDataSource(c,uri),new ShadowMediaPlayer.MediaInfo(135000,10));
        org.robolectric.android.controller.ServiceController<PlaybackService> service=Robolectric.buildService(PlaybackService.class).create();PlaybackService s=service.get();s.onStartCommand(new Intent(c,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","1"),0,1);Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(100,TimeUnit.MILLISECONDS);
        assertTrue(PlaybackService.prepared);assertTrue(PlaybackService.playing);assertEquals("1",PlaybackService.currentId);PlaybackService.seek(5000);Shadows.shadowOf(android.os.Looper.getMainLooper()).idleFor(100,TimeUnit.MILLISECONDS);assertTrue(PlaybackService.position()>=5000);
        c.sendBroadcast(new Intent(android.media.AudioManager.ACTION_AUDIO_BECOMING_NOISY));Shadows.shadowOf(android.os.Looper.getMainLooper()).idle();assertFalse(PlaybackService.playing);
        s.onStartCommand(new Intent(c,PlaybackService.class).setAction(PlaybackService.PLAY).putExtra("id","1"),0,2);assertTrue(PlaybackService.playing);s.onStartCommand(new Intent(c,PlaybackService.class).setAction(PlaybackService.CLOSE),0,3);assertEquals("",PlaybackService.currentId);assertFalse(PlaybackService.prepared);service.destroy();
    }
}
