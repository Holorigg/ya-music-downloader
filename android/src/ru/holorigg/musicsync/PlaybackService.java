package ru.holorigg.musicsync;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.media.*;
import android.media.session.*;
import android.net.Uri;
import android.os.*;
import org.json.JSONObject;
import java.io.File;
import java.util.*;

public final class PlaybackService extends Service {
    static final String PLAY="ru.holorigg.musicsync.PLAY", PAUSE="ru.holorigg.musicsync.PAUSE", CLOSE="ru.holorigg.musicsync.CLOSE";
    static final String NEXT="ru.holorigg.musicsync.NEXT", PREVIOUS="ru.holorigg.musicsync.PREVIOUS";
    private static final String PREF_SHUFFLE="playback_shuffle", PREF_REPEAT="playback_repeat";
    public static final int REPEAT_OFF=0, REPEAT_ALL=1, REPEAT_ONE=2;
    static volatile String currentId=""; static volatile JSONObject currentTrack=new JSONObject();
    static volatile boolean playing=false, loading=false, prepared=false;
    private static volatile PlaybackService instance;
    private static volatile boolean shuffleMode=false;
    private static volatile int repeatMode=REPEAT_OFF;
    private final PlaybackQueue queue=new PlaybackQueue();
    private MediaPlayer player; private MediaSession session; private Store store; private AudioManager audio;
    private AudioFocusRequest focus; private boolean resumeAfterFocus=false, wantsPlayback=false, foreground=false; private Bitmap cover;
    private final Set<String> failedIds=new HashSet<>();
    private String attemptId="";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final BroadcastReceiver unplug=new BroadcastReceiver(){public void onReceive(Context c,Intent i){resumeAfterFocus=false;wantsPlayback=false;pausePlayer();}};
    private final Runnable update=new Runnable(){public void run(){if(player!=null&&prepared){state();if(playing)handler.postDelayed(this,1000);}}};

    static void configure(Context c){SharedPreferences p=c.getApplicationContext().getSharedPreferences("settings",Context.MODE_PRIVATE);shuffleMode=p.getBoolean(PREF_SHUFFLE,false);repeatMode=Math.max(REPEAT_OFF,Math.min(REPEAT_ONE,p.getInt(PREF_REPEAT,REPEAT_OFF)));}
    static void play(Context c,String id){start(c,new Intent(c,PlaybackService.class).setAction(PLAY).putExtra("id",id));}
    static void play(Context c,String id,List<String> ids){Intent i=new Intent(c,PlaybackService.class).setAction(PLAY).putExtra("id",id);if(ids!=null)i.putStringArrayListExtra("queue",new ArrayList<>(ids));start(c,i);}
    private static void start(Context c,Intent i){if(Build.VERSION.SDK_INT>=26)c.startForegroundService(i);else c.startService(i);}
    static void toggle(Context c){if(currentId.isEmpty())return;PlaybackService s=instance;Intent i=new Intent(c,PlaybackService.class).setAction(playing||loading&&s!=null&&s.wantsPlayback?PAUSE:PLAY).putExtra("id",currentId);if(PAUSE.equals(i.getAction()))c.startService(i);else start(c,i);}
    static void next(Context c){start(c,new Intent(c,PlaybackService.class).setAction(NEXT));}
    static void previous(Context c){start(c,new Intent(c,PlaybackService.class).setAction(PREVIOUS));}
    static void toggleShuffle(Context c){PlaybackService s=instance;if(s!=null)c.startService(new Intent(c,PlaybackService.class).setAction("TOGGLE_SHUFFLE"));else{configure(c);shuffleMode=!shuffleMode;c.getApplicationContext().getSharedPreferences("settings",Context.MODE_PRIVATE).edit().putBoolean(PREF_SHUFFLE,shuffleMode).apply();}}
    static void cycleRepeat(Context c){PlaybackService s=instance;if(s!=null)c.startService(new Intent(c,PlaybackService.class).setAction("CYCLE_REPEAT"));else{configure(c);repeatMode=(repeatMode+1)%3;c.getApplicationContext().getSharedPreferences("settings",Context.MODE_PRIVATE).edit().putInt(PREF_REPEAT,repeatMode).apply();}}
    static boolean isShuffle(){return shuffleMode;}
    static int repeatMode(){return repeatMode;}
    static boolean playRequested(){PlaybackService s=instance;return s!=null&&s.wantsPlayback;}
    static boolean canNext(){PlaybackService s=instance;if(s==null)return !currentId.isEmpty();if(!s.queue.canNext(repeatMode==REPEAT_ALL))return false;for(String id:s.queue.ids())if(!s.failedIds.contains(id))return true;return false;}
    static boolean canPrevious(){PlaybackService s=instance;return s!=null?(position()>0||s.queue.canPrevious(repeatMode==REPEAT_ALL)):!currentId.isEmpty();}
    static List<String> queueIds(){PlaybackService s=instance;return s==null?new ArrayList<>():s.queue.ids();}
    static void close(Context c){if(instance!=null)c.startService(new Intent(c,PlaybackService.class).setAction(CLOSE));}
    static long position(){PlaybackService s=instance;if(s==null||s.player==null||!prepared)return 0;try{return s.player.getCurrentPosition();}catch(Exception e){return 0;}}
    static long duration(){PlaybackService s=instance;if(s==null||s.player==null||!prepared)return 0;try{return s.player.getDuration();}catch(Exception e){return 0;}}
    static void seek(int ms){PlaybackService s=instance;if(s!=null&&s.player!=null&&prepared)try{s.player.seekTo(Math.max(0,Math.min(ms,s.player.getDuration())));s.state();}catch(Exception ignored){}}

    @Override public void onCreate(){super.onCreate();instance=this;store=new Store(this);configure(this);queue.setShuffle(shuffleMode);audio=getSystemService(AudioManager.class);getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel("music_playback","Плеер",NotificationManager.IMPORTANCE_LOW));
        AudioAttributes attributes=new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();
        focus=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setAudioAttributes(attributes).setOnAudioFocusChangeListener(change->{
            if(change==AudioManager.AUDIOFOCUS_LOSS){resumeAfterFocus=false;wantsPlayback=false;pausePlayer();}
            else if(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT){resumeAfterFocus=wantsPlayback;if(player!=null&&prepared&&playing)try{player.pause();}catch(Exception ignored){}playing=false;wantsPlayback=false;handler.removeCallbacks(update);state();}
            else if(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK){if(player!=null&&prepared)player.setVolume(.25f,.25f);}
            else if(change==AudioManager.AUDIOFOCUS_GAIN){if(player!=null&&prepared)player.setVolume(1,1);if(resumeAfterFocus){resumeAfterFocus=false;wantsPlayback=true;resume();}}
        },handler).build();
        session=new MediaSession(this,"MyMusic");session.setCallback(new MediaSession.Callback(){public void onPlay(){wantsPlayback=true;if(prepared)resume();}public void onPause(){resumeAfterFocus=false;wantsPlayback=false;pausePlayer();}public void onStop(){finish();}public void onSkipToNext(){advance(false);}public void onSkipToPrevious(){goPrevious();}public void onCustomAction(String action,Bundle extras){if(CLOSE.equals(action))finish();}public void onSeekTo(long position){seek((int)Math.min(Integer.MAX_VALUE,position));}});session.setActive(true);
        IntentFilter filter=new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY);if(Build.VERSION.SDK_INT>=33)registerReceiver(unplug,filter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(unplug,filter);
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent==null){finish();return START_NOT_STICKY;}String action=intent.getAction();
        if(CLOSE.equals(action)){finish();return START_NOT_STICKY;}if(PAUSE.equals(action)){resumeAfterFocus=false;wantsPlayback=false;pausePlayer();return START_NOT_STICKY;}
        if("TOGGLE_SHUFFLE".equals(action)){shuffleMode=!shuffleMode;store.prefs.edit().putBoolean(PREF_SHUFFLE,shuffleMode).apply();queue.setShuffle(shuffleMode);state();return START_NOT_STICKY;}
        if("CYCLE_REPEAT".equals(action)){repeatMode=(repeatMode+1)%3;store.prefs.edit().putInt(PREF_REPEAT,repeatMode).apply();state();return START_NOT_STICKY;}
        if(NEXT.equals(action)){promote();advance(false);return START_NOT_STICKY;}if(PREVIOUS.equals(action)){promote();goPrevious();return START_NOT_STICKY;}
        if(PLAY.equals(action)){
            promote();String id=intent.getStringExtra("id");if(id==null||id.isEmpty())id=currentId;
            if(id.equals(currentId)&&prepared){wantsPlayback=true;resume();return START_NOT_STICKY;}if(id.equals(currentId)&&loading){wantsPlayback=true;return START_NOT_STICKY;}
            List<String> supplied=intent.getStringArrayListExtra("queue");if(supplied!=null)configureQueue(supplied,id);else configureQueue(defaultQueue(id),id);
            wantsPlayback=true;failedIds.clear();load(id);
        }return START_NOT_STICKY;
    }
    private List<String> defaultQueue(String id){List<String> ids=new ArrayList<>();JSONObject row=store.row(Net.id(id));boolean archive=row!=null&&"0".equals(row.optString("liked"));for(JSONObject r:store.rows("status='downloaded' AND "+(archive?"liked=0 AND archive_hidden=0":"liked=1")))ids.add(r.optString("id"));if(!ids.contains(id))ids.add(id);return ids;}
    private void configureQueue(List<String> ids,String id){queue.setQueue(ids,id);queue.setShuffle(shuffleMode);queue.accepted(id);}
    private void promote(){if(Build.VERSION.SDK_INT>=29)startForeground(88,notification(),ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);else startForeground(88,notification());foreground=true;}
    private void load(String id){
        try{queue.accepted(id);attemptId=id;JSONObject row=store.row(Net.id(id));if(row==null||!"downloaded".equals(row.optString("status")))throw new IllegalArgumentException("Трек не скачан");releasePlayer();currentId=id;currentTrack=Store.metadata(row);loading=true;playing=false;prepared=false;cover=null;
            File art=Ui.coverFile(this,currentTrack);if(art!=null&&art.isFile())cover=Ui.decodeCover(art,320);
            session.setMetadata(new MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE,currentTrack.optString("title")).putString(MediaMetadata.METADATA_KEY_ARTIST,Store.artist(currentTrack)).putString(MediaMetadata.METADATA_KEY_ALBUM,Store.album(currentTrack).optString("title")).putLong(MediaMetadata.METADATA_KEY_DURATION,currentTrack.optLong("durationMs")).putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART,cover).build());
            MediaPlayer candidate=new MediaPlayer();player=candidate;candidate.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());candidate.setWakeMode(this,PowerManager.PARTIAL_WAKE_LOCK);
            candidate.setOnPreparedListener(p->{if(p!=player)return;loading=false;prepared=true;if(wantsPlayback)resume();else{state();demote();}});candidate.setOnCompletionListener(p->{if(p!=player)return;playing=false;resumeAfterFocus=false;audio.abandonAudioFocusRequest(focus);if(repeatMode==REPEAT_ONE){try{p.seekTo(0);if(wantsPlayback)resume();else{state();demote();}}catch(Exception e){advance(true);}}else advance(true);});
            candidate.setOnErrorListener((p,what,extra)->{if(p==player)broken();return true;});candidate.setDataSource(this,Uri.parse(row.getString("uri")));candidate.prepareAsync();state();
        }catch(Exception e){loading=false;prepared=false;broken();}
    }
    private boolean advance(boolean automatic){
        if(queue.size()==0){if(automatic)finish();else demote();return false;}if(automatic&&repeatMode==REPEAT_ONE&&player!=null&&prepared){try{player.seekTo(0);if(wantsPlayback)resume();else{state();demote();}return true;}catch(Exception ignored){}}
        String id=null;for(int n=0;n<queue.size();n++){String candidate=queue.next(repeatMode==REPEAT_ALL);if(candidate==null)break;queue.accepted(candidate);if(!failedIds.contains(candidate)){id=candidate;break;}}
        if(id==null){if(automatic){if(player!=null&&prepared)try{if(player.isPlaying())player.pause();}catch(Exception ignored){}playing=false;wantsPlayback=false;state();demote();}else if(!playing)demote();return false;}load(id);return true;
    }
    private void goPrevious(){if(prepared&&position()>3000){seek(0);if(!playing)demote();return;}String id=queue.previous(repeatMode==REPEAT_ALL);if(id==null){if(prepared)seek(0);if(!playing)demote();return;}load(id);}
    private void broken(){String failed=attemptId;if(!failed.isEmpty())failedIds.add(failed);releasePlayer();if(failedIds.size()<Math.max(1,queue.size())&&advance(false))return;wantsPlayback=false;resumeAfterFocus=false;audio.abandonAudioFocusRequest(focus);android.widget.Toast.makeText(this,"Не удалось открыть треки. Проверь доступ к папке.",android.widget.Toast.LENGTH_LONG).show();state();demote();}
    private void resume(){if(player==null||!prepared)return;try{promote();if(audio.requestAudioFocus(focus)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED){wantsPlayback=false;pausePlayer();return;}player.setVolume(1,1);if(player.getCurrentPosition()>=player.getDuration())player.seekTo(0);player.start();playing=true;wantsPlayback=true;resumeAfterFocus=false;final String startedId=currentId;final MediaPlayer startedPlayer=player;handler.postDelayed(()->{if(startedPlayer==player&&playing&&startedId.equals(currentId)&&position()>0)failedIds.clear();},1500);state();handler.removeCallbacks(update);handler.post(update);}catch(Exception e){broken();}}
    private void pausePlayer(){if(player!=null&&prepared)try{if(player.isPlaying())player.pause();}catch(Exception ignored){}playing=false;audio.abandonAudioFocusRequest(focus);handler.removeCallbacks(update);state();demote();}
    private void demote(){if(foreground){stopForeground(STOP_FOREGROUND_DETACH);foreground=false;}if(!currentId.isEmpty())getSystemService(NotificationManager.class).notify(88,notification());}
    private void state(){if(session==null)return;long actions=PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PAUSE|PlaybackState.ACTION_PLAY_PAUSE|PlaybackState.ACTION_STOP|PlaybackState.ACTION_SEEK_TO;if(canNext())actions|=PlaybackState.ACTION_SKIP_TO_NEXT;if(canPrevious())actions|=PlaybackState.ACTION_SKIP_TO_PREVIOUS;int state=loading?PlaybackState.STATE_BUFFERING:playing?PlaybackState.STATE_PLAYING:PlaybackState.STATE_PAUSED;session.setPlaybackState(new PlaybackState.Builder().setActions(actions).setState(state,position(),playing?1:0).addCustomAction(CLOSE,"Закрыть",R.drawable.ic_close).build());if(!currentId.isEmpty())getSystemService(NotificationManager.class).notify(88,notification());}
    private PendingIntent serviceIntent(String action,int request){Intent i=new Intent(this,PlaybackService.class).setAction(action);int flags=PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE;return Build.VERSION.SDK_INT>=26?PendingIntent.getForegroundService(this,request,i,flags):PendingIntent.getService(this,request,i,flags);}
    private PendingIntent closeIntent(){return PendingIntent.getService(this,90,new Intent(this,PlaybackService.class).setAction(CLOSE),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    Notification notification(){
        Intent open=new Intent(this,MainActivity.class).putExtra("song",currentId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);PendingIntent content=PendingIntent.getActivity(this,88,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        boolean active=playing||loading&&wantsPlayback;Intent toggle=new Intent(this,PlaybackService.class).setAction(active?PAUSE:PLAY).putExtra("id",currentId);PendingIntent action=active?PendingIntent.getService(this,89,toggle,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE):PendingIntent.getForegroundService(this,89,toggle,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        PendingIntent close=closeIntent();
        Notification.Builder builder=new Notification.Builder(this,"music_playback").setSmallIcon(R.drawable.ic_notification).setContentTitle(currentTrack.optString("title","Моя музыка")).setContentText(loading?"Открываем трек…":Store.artist(currentTrack)).setContentIntent(content).setDeleteIntent(close).setOnlyAlertOnce(true).setShowWhen(false).setCategory(Notification.CATEGORY_TRANSPORT).setVisibility(Notification.VISIBILITY_PUBLIC).setOngoing(playing||loading)
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,R.drawable.ic_skip_previous),"Предыдущий",serviceIntent(PREVIOUS,91)).build())
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,active?R.drawable.ic_pause:R.drawable.ic_play),active?"Пауза":"Продолжить",action).build())
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,R.drawable.ic_skip_next),"Следующий",serviceIntent(NEXT,92)).build())
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,R.drawable.ic_close),"Закрыть",close).build());
        if(cover!=null)builder.setLargeIcon(cover);if(session!=null)builder.setStyle(new Notification.MediaStyle().setMediaSession(session.getSessionToken()).setShowActionsInCompactView(0,1,2));return builder.build();
    }
    private void releasePlayer(){handler.removeCallbacks(update);prepared=false;playing=false;loading=false;if(player!=null){player.setOnPreparedListener(null);player.setOnCompletionListener(null);player.setOnErrorListener(null);player.release();player=null;}}
    private void finish(){wantsPlayback=false;resumeAfterFocus=false;releasePlayer();audio.abandonAudioFocusRequest(focus);currentId="";currentTrack=new JSONObject();stopForeground(STOP_FOREGROUND_REMOVE);foreground=false;getSystemService(NotificationManager.class).cancel(88);stopSelf();}
    @Override public void onDestroy(){handler.removeCallbacksAndMessages(null);releasePlayer();audio.abandonAudioFocusRequest(focus);try{unregisterReceiver(unplug);}catch(Exception ignored){}if(session!=null){session.setActive(false);session.release();}if(store!=null)store.close();currentId="";currentTrack=new JSONObject();instance=null;getSystemService(NotificationManager.class).cancel(88);super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
