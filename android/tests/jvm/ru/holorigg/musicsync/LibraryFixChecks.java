package ru.holorigg.musicsync;

import android.content.*;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.Color;
import android.os.Looper;
import android.view.*;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.*;
import androidx.appcompat.app.AppCompatDelegate;
import androidx.coordinatorlayout.widget.CoordinatorLayout;
import androidx.core.content.ContextCompat;
import androidx.core.view.ViewCompat;
import androidx.recyclerview.widget.RecyclerView;
import com.google.android.material.behavior.SwipeDismissBehavior;
import com.google.android.material.color.DynamicColors;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import org.robolectric.*;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk=35,qualifiers="w360dp-h800dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.LEGACY)
public class LibraryFixChecks {
    private Store store;private ActivityController<MainActivity> controller;
    private Context context(){return RuntimeEnvironment.getApplication();}
    @Before public void before(){Context c=context();c.getSharedPreferences("settings",0).edit().clear().putInt("theme",AppCompatDelegate.MODE_NIGHT_NO).commit();c.deleteDatabase("music.db");store=new Store(c);Store.revision.incrementAndGet();SyncEngine.running.set(false);SyncEngine.stop.set(false);PlaybackService.currentId="";}
    @After public void after(){SyncEngine.running.set(false);if(controller!=null)controller.pause().stop().destroy();store.close();}
    private MainActivity open()throws Exception{controller=Robolectric.buildActivity(MainActivity.class).setup();settle();return controller.get();}
    private void settle()throws Exception{for(int n=0;n<30;n++){Thread.sleep(20);Shadows.shadowOf(Looper.getMainLooper()).idle();}View v=controller.get().getWindow().getDecorView();v.measure(View.MeasureSpec.makeMeasureSpec(360,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(800,View.MeasureSpec.EXACTLY));v.layout(0,0,360,800);}
    private Map<String,JSONObject> seed()throws Exception{Map<String,JSONObject> tracks=new HashMap<>();for(int n=1;n<=3;n++)tracks.put(""+n,new JSONObject().put("id",""+n).put("title","Песня "+n).put("available",true));store.catalog(Arrays.asList("1","2","3"),tracks);ContentValues v=new ContentValues();v.put("status","downloaded");v.put("uri","content://music/original");v.put("sha","original-sha");store.update("1",v);store.update("3",v);store.fail("2","Недоступна");store.catalog(Arrays.asList("1","2"),tracks);return tracks;}
    private int count(MainActivity a){return ((RecyclerView)a.findViewById(R.id.library_list)).getAdapter().getItemCount();}
    @Test public void archiveHasItsOwnFilterAndClearKeepsFiles()throws Exception{
        seed();MainActivity a=open();assertEquals(2,count(a));a.findViewById(R.id.filter_downloaded).performClick();assertEquals(1,count(a));a.findViewById(R.id.filter_missing).performClick();assertEquals(1,count(a));a.findViewById(R.id.filter_archive).performClick();assertEquals(1,count(a));assertEquals(View.VISIBLE,a.findViewById(R.id.archive_clear).getVisibility());
        a.findViewById(R.id.archive_clear).performClick();settle();assertEquals(0,count(a));assertEquals(View.GONE,a.findViewById(R.id.archive_clear).getVisibility());JSONObject original=store.row("3");assertEquals("content://music/original",original.getString("uri"));assertEquals("original-sha",original.getString("sha"));assertEquals("downloaded",original.getString("status"));
        store.restoreArchive(Collections.singletonList("3"));Shadows.shadowOf(Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);settle();assertEquals(1,count(a));
    }
    @Test public void removingOneArchiveSongAndRelikingDoesNotRedownload()throws Exception{
        Map<String,JSONObject> tracks=seed();MainActivity a=open();a.findViewById(R.id.filter_archive).performClick();settle();RecyclerView list=a.findViewById(R.id.library_list);ViewGroup row=(ViewGroup)list.getChildAt(0);View action=row.getChildAt(row.getChildCount()-1);assertTrue(action.getContentDescription().toString().startsWith("Убрать из архива"));action.performClick();settle();assertEquals(0,count(a));
        store.catalog(Arrays.asList("1","2","3"),tracks);assertEquals("0",store.row("3").getString("archive_hidden"));assertEquals("downloaded",store.row("3").getString("status"));assertEquals("original-sha",store.row("3").getString("sha"));Shadows.shadowOf(Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);settle();a.findViewById(R.id.filter_all).performClick();assertEquals(3,count(a));
        assertTrue(store.hideArchive(Collections.singletonList("1")).isEmpty());
    }
    @Test public void versionOneDatabaseMigratesWithoutLosingMusicOrSettings()throws Exception{
        store.close();Context c=context();java.io.File path=c.getDatabasePath("music.db");path.getParentFile().mkdirs();try(SQLiteDatabase old=SQLiteDatabase.openOrCreateDatabase(path,null)){
            old.execSQL("CREATE TABLE tracks(id TEXT PRIMARY KEY,position INTEGER,liked INTEGER DEFAULT 1,metadata TEXT,status TEXT DEFAULT 'pending',uri TEXT,tree TEXT,name TEXT,sha TEXT,size INTEGER,error TEXT,cover TEXT DEFAULT 'pending',lyrics TEXT DEFAULT 'pending',pending_uri TEXT,pending_sha TEXT,pending_size INTEGER,pending_tree TEXT,pending_name TEXT,pending_cover TEXT,pending_lyrics TEXT)");
            old.execSQL("INSERT INTO tracks(id,liked,metadata,status,uri,sha,pending_uri) VALUES('9',0,'{}','downloaded','content://music/kept','verified-sha','content://music/pending')");old.setVersion(1);
        }
        c.getSharedPreferences("settings",0).edit().putString("auth","existing-encrypted-auth").putString("tree","existing-folder").commit();store=new Store(c);JSONObject row=store.row("9");assertEquals("0",row.getString("archive_hidden"));assertEquals("verified-sha",row.getString("sha"));assertEquals("content://music/pending",row.getString("pending_uri"));assertEquals(2,store.getReadableDatabase().getVersion());assertEquals("existing-encrypted-auth",store.prefs.getString("auth",""));assertEquals("existing-folder",store.prefs.getString("tree",""));
    }
    @Test public void dismissalSurvivesRefreshAndReopenButNewResultAppears()throws Exception{
        store.prefs.edit().putString("last_outcome","done").putInt("last_missing",1).putLong("last_result_at",100).commit();MainActivity a=open();View card=a.findViewById(R.id.sync_panel);assertEquals(View.VISIBLE,card.getVisibility());assertTrue(ViewCompat.performAccessibilityAction(card,AccessibilityNodeInfo.ACTION_DISMISS,null));assertEquals(View.GONE,card.getVisibility());Shadows.shadowOf(Looper.getMainLooper()).idleFor(3,TimeUnit.SECONDS);assertEquals(View.GONE,card.getVisibility());
        controller.pause().stop().destroy();controller=null;a=open();assertEquals(View.GONE,a.findViewById(R.id.sync_panel).getVisibility());store.prefs.edit().putLong("last_result_at",200).commit();Shadows.shadowOf(Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);assertEquals(View.VISIBLE,a.findViewById(R.id.sync_panel).getVisibility());assertEquals(1f,a.findViewById(R.id.sync_panel).getAlpha(),.001f);
        SyncEngine.begin(false);Shadows.shadowOf(Looper.getMainLooper()).idleFor(1,TimeUnit.SECONDS);SwipeDismissBehavior<?> swipe=(SwipeDismissBehavior<?>)((CoordinatorLayout.LayoutParams)a.findViewById(R.id.sync_panel).getLayoutParams()).getBehavior();assertFalse(swipe.canSwipeDismissView(a.findViewById(R.id.sync_panel)));assertFalse(ViewCompat.performAccessibilityAction(a.findViewById(R.id.sync_panel),AccessibilityNodeInfo.ACTION_DISMISS,null));
    }
    @Test public void idleBannerCanBeSwipedWithTouch()throws Exception{
        store.prefs.edit().putString("last_outcome","done").putInt("last_missing",1).putLong("last_result_at",100).commit();MainActivity a=open();ViewGroup host=a.findViewById(R.id.sync_host);float y=host.getHeight()/2f;long time=android.os.SystemClock.uptimeMillis();
        for(int step=0;step<=7;step++){int action=step==0?MotionEvent.ACTION_DOWN:step==7?MotionEvent.ACTION_UP:MotionEvent.ACTION_MOVE;MotionEvent e=MotionEvent.obtain(time,time+step*40,action,80+step*40,y,0);host.dispatchTouchEvent(e);e.recycle();Shadows.shadowOf(Looper.getMainLooper()).idleFor(40,TimeUnit.MILLISECONDS);}Shadows.shadowOf(Looper.getMainLooper()).idleFor(2,TimeUnit.SECONDS);assertEquals(View.GONE,host.getVisibility());assertFalse(store.prefs.getString("dismissed_banner_key","").isEmpty());
    }
    @Test public void searchIsCenteredAndFourFiltersFit360dp()throws Exception{
        MainActivity a=open();EditText input=a.findViewById(R.id.search);assertEquals(0,input.getPaddingTop());assertEquals(0,input.getPaddingBottom());assertEquals(Gravity.CENTER_VERTICAL,input.getGravity()&Gravity.VERTICAL_GRAVITY_MASK);View icon=a.findViewById(R.id.search_icon);int[] aPos=new int[2],bPos=new int[2];input.getLocationOnScreen(aPos);icon.getLocationOnScreen(bPos);assertEquals(aPos[1]+input.getHeight()/2,bPos[1]+icon.getHeight()/2);View archive=a.findViewById(R.id.filter_archive);archive.getLocationOnScreen(aPos);assertTrue("All four filters should fit at normal font scale",aPos[0]+archive.getWidth()<=340);input.setText("тест");assertEquals(View.VISIBLE,a.findViewById(R.id.search_clear).getVisibility());a.findViewById(R.id.search_clear).performClick();assertEquals("",input.getText().toString());
    }
    @Test @Config(qualifiers="w360dp-h800dp-night-mdpi") public void forcedDarkSurfacesAreNeutral()throws Exception{
        store.prefs.edit().putInt("theme",AppCompatDelegate.MODE_NIGHT_YES).commit();MainActivity a=open();for(int role:new int[]{R.color.surface,R.color.surface_low,R.color.surface_container,R.color.surface_high}){int value=Ui.color(a,role);assertEquals(Color.red(value),Color.green(value));assertEquals(Color.red(value),Color.blue(value));assertTrue(Color.red(value)<50);}assertEquals(ContextCompat.getColor(a,R.color.primary),Ui.color(a,R.color.primary));
    }
    @Test public void phoneModeUsesTheMaterialYouPalette()throws Exception{
        store.prefs.edit().putInt("theme",AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM).commit();assertTrue(DynamicColors.isDynamicColorAvailable());MainActivity a=open();android.util.TypedValue value=new android.util.TypedValue();assertTrue(a.getTheme().resolveAttribute(androidx.appcompat.R.attr.colorPrimary,value,true));int themed=value.resourceId==0?value.data:ContextCompat.getColor(a,value.resourceId);assertEquals(themed,Ui.color(a,R.color.primary));assertNotEquals("Phone accent must override the forced blue palette",ContextCompat.getColor(a,R.color.primary),Ui.color(a,R.color.primary));
    }
}
