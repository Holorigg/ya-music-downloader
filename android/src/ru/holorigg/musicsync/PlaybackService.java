package ru.holorigg.musicsync;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.*;
import android.media.*;
import android.media.session.*;
import android.net.Uri;
import android.os.*;
import org.json.JSONObject;
import java.io.File;

public final class PlaybackService extends Service {
    static final String PLAY="ru.holorigg.musicsync.PLAY",PAUSE="ru.holorigg.musicsync.PAUSE",CLOSE="ru.holorigg.musicsync.CLOSE";
    static volatile String currentId="";static volatile JSONObject currentTrack=new JSONObject();
    static volatile boolean playing=false,loading=false,prepared=false;
    private static volatile PlaybackService instance;
    private MediaPlayer player;private MediaSession session;private Store store;private AudioManager audio;
    private AudioFocusRequest focus;private boolean resumeAfterFocus=false,foreground=false;private Bitmap cover;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final BroadcastReceiver unplug=new BroadcastReceiver(){public void onReceive(Context c,Intent i){pause();}};
    private final Runnable update=new Runnable(){public void run(){if(player!=null&&prepared){state();if(playing)handler.postDelayed(this,1000);}}};

    static void play(Context c,String id){c.startForegroundService(new Intent(c,PlaybackService.class).setAction(PLAY).putExtra("id",id));}
    static void toggle(Context c){if(currentId.isEmpty())return;Intent i=new Intent(c,PlaybackService.class).setAction(playing?PAUSE:PLAY).putExtra("id",currentId);if(playing)c.startService(i);else c.startForegroundService(i);}
    static void close(Context c){if(instance!=null)c.startService(new Intent(c,PlaybackService.class).setAction(CLOSE));}
    static long position(){PlaybackService s=instance;if(s==null||s.player==null||!prepared)return 0;try{return s.player.getCurrentPosition();}catch(Exception e){return 0;}}
    static long duration(){PlaybackService s=instance;if(s==null||s.player==null||!prepared)return 0;try{return s.player.getDuration();}catch(Exception e){return 0;}}
    static void seek(int ms){PlaybackService s=instance;if(s!=null&&s.player!=null&&prepared)try{s.player.seekTo(Math.max(0,Math.min(ms,s.player.getDuration())));s.state();}catch(Exception ignored){}}
    @Override public void onCreate(){super.onCreate();instance=this;store=new Store(this);audio=getSystemService(AudioManager.class);getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel("music_playback","Плеер",NotificationManager.IMPORTANCE_LOW));
        AudioAttributes attributes=new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();
        focus=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setAudioAttributes(attributes).setOnAudioFocusChangeListener(change->{
            if(change==AudioManager.AUDIOFOCUS_LOSS){resumeAfterFocus=false;pause();}
            else if(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT){resumeAfterFocus=playing;if(player!=null&&prepared&&playing)try{player.pause();}catch(Exception ignored){}playing=false;handler.removeCallbacks(update);state();}
            else if(change==AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK){if(player!=null&&prepared)player.setVolume(.25f,.25f);}
            else if(change==AudioManager.AUDIOFOCUS_GAIN){if(player!=null&&prepared)player.setVolume(1,1);if(resumeAfterFocus){resumeAfterFocus=false;resume();}}
        },handler).build();
        session=new MediaSession(this,"MyMusic");session.setCallback(new MediaSession.Callback(){public void onPlay(){resume();}public void onPause(){resumeAfterFocus=false;pause();}public void onStop(){finish();}public void onCustomAction(String action,Bundle extras){if(CLOSE.equals(action))finish();}public void onSeekTo(long position){seek((int)Math.min(Integer.MAX_VALUE,position));}});session.setActive(true);
        IntentFilter filter=new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY);if(Build.VERSION.SDK_INT>=33)registerReceiver(unplug,filter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(unplug,filter);
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent==null){finish();return START_NOT_STICKY;}String action=intent.getAction();if(CLOSE.equals(action)){finish();return START_NOT_STICKY;}if(PAUSE.equals(action)){resumeAfterFocus=false;pause();return START_NOT_STICKY;}
        if(PLAY.equals(action)){
            // Fulfil startForegroundService before I/O or audio focus on Android 15.
            promote();String id=intent.getStringExtra("id");if(id==null||id.isEmpty())id=currentId;
            if(id.equals(currentId)&&prepared){resume();return START_NOT_STICKY;}if(id.equals(currentId)&&loading)return START_NOT_STICKY;
            load(id);
        }return START_NOT_STICKY;
    }
    private void promote(){if(Build.VERSION.SDK_INT>=29)startForeground(88,notification(),ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);else startForeground(88,notification());foreground=true;}
    private void load(String id){
        try{JSONObject row=store.row(Net.id(id));if(row==null||!"downloaded".equals(row.optString("status")))throw new IllegalArgumentException("Трек не скачан");releasePlayer();currentId=id;currentTrack=Store.metadata(row);loading=true;playing=false;prepared=false;cover=null;
            File art=Ui.coverFile(this,currentTrack);if(art!=null&&art.isFile())cover=Ui.decodeCover(art,320);
            session.setMetadata(new MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE,currentTrack.optString("title")).putString(MediaMetadata.METADATA_KEY_ARTIST,Store.artist(currentTrack)).putString(MediaMetadata.METADATA_KEY_ALBUM,Store.album(currentTrack).optString("title")).putLong(MediaMetadata.METADATA_KEY_DURATION,currentTrack.optLong("durationMs")).putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART,cover).build());
            MediaPlayer candidate=new MediaPlayer();player=candidate;candidate.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());candidate.setWakeMode(this,PowerManager.PARTIAL_WAKE_LOCK);
            candidate.setOnPreparedListener(p->{if(p!=player)return;loading=false;prepared=true;resume();});candidate.setOnCompletionListener(p->{playing=false;resumeAfterFocus=false;audio.abandonAudioFocusRequest(focus);state();demote();});
            candidate.setOnErrorListener((p,what,extra)->{fail();return true;});candidate.setDataSource(this,Uri.parse(row.getString("uri")));candidate.prepareAsync();state();
        }catch(Exception e){fail();}
    }
    private void resume(){if(player==null||!prepared)return;try{promote();if(audio.requestAudioFocus(focus)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED){pause();return;}player.setVolume(1,1);if(player.getCurrentPosition()>=player.getDuration())player.seekTo(0);player.start();playing=true;resumeAfterFocus=false;state();handler.removeCallbacks(update);handler.post(update);}catch(Exception e){fail();}}
    private void pause(){if(player!=null&&prepared)try{if(player.isPlaying())player.pause();}catch(Exception ignored){}playing=false;audio.abandonAudioFocusRequest(focus);handler.removeCallbacks(update);state();demote();}
    private void demote(){if(foreground){stopForeground(STOP_FOREGROUND_DETACH);foreground=false;}if(!currentId.isEmpty())getSystemService(NotificationManager.class).notify(88,notification());}
    private void state(){if(session==null)return;long actions=PlaybackState.ACTION_PLAY|PlaybackState.ACTION_PAUSE|PlaybackState.ACTION_PLAY_PAUSE|PlaybackState.ACTION_STOP|PlaybackState.ACTION_SEEK_TO;int state=loading?PlaybackState.STATE_BUFFERING:playing?PlaybackState.STATE_PLAYING:PlaybackState.STATE_PAUSED;session.setPlaybackState(new PlaybackState.Builder().setActions(actions).setState(state,position(),playing?1:0).addCustomAction(CLOSE,"Закрыть",R.drawable.ic_close).build());if(!currentId.isEmpty())getSystemService(NotificationManager.class).notify(88,notification());}
    Notification notification(){
        Intent open=new Intent(this,MainActivity.class).putExtra("song",currentId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent content=PendingIntent.getActivity(this,88,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Intent toggle=new Intent(this,PlaybackService.class).setAction(playing?PAUSE:PLAY).putExtra("id",currentId);PendingIntent action=playing?PendingIntent.getService(this,89,toggle,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE):PendingIntent.getForegroundService(this,89,toggle,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        PendingIntent close=PendingIntent.getService(this,90,new Intent(this,PlaybackService.class).setAction(CLOSE),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder=new Notification.Builder(this,"music_playback").setSmallIcon(R.drawable.ic_notification).setContentTitle(currentTrack.optString("title","Моя музыка")).setContentText(loading?"Открываем трек…":Store.artist(currentTrack)).setContentIntent(content).setDeleteIntent(close).setOnlyAlertOnce(true).setShowWhen(false).setCategory(Notification.CATEGORY_TRANSPORT).setVisibility(Notification.VISIBILITY_PUBLIC).setOngoing(playing||loading)
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,playing?R.drawable.ic_pause:R.drawable.ic_play),playing?"Пауза":"Продолжить",action).build())
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,R.drawable.ic_close),"Закрыть",close).build());
        if(cover!=null)builder.setLargeIcon(cover);if(session!=null)builder.setStyle(new Notification.MediaStyle().setMediaSession(session.getSessionToken()).setShowActionsInCompactView(0,1));return builder.build();
    }
    private void fail(){android.widget.Toast.makeText(this,"Не удалось открыть трек. Проверь доступ к папке.",android.widget.Toast.LENGTH_LONG).show();finish();}
    private void releasePlayer(){handler.removeCallbacks(update);prepared=false;playing=false;loading=false;if(player!=null){player.setOnPreparedListener(null);player.setOnCompletionListener(null);player.setOnErrorListener(null);player.release();player=null;}}
    private void finish(){releasePlayer();audio.abandonAudioFocusRequest(focus);currentId="";currentTrack=new JSONObject();stopForeground(STOP_FOREGROUND_REMOVE);foreground=false;getSystemService(NotificationManager.class).cancel(88);stopSelf();}
    @Override public void onDestroy(){handler.removeCallbacksAndMessages(null);releasePlayer();audio.abandonAudioFocusRequest(focus);try{unregisterReceiver(unplug);}catch(Exception ignored){}if(session!=null){session.setActive(false);session.release();}if(store!=null)store.close();currentId="";currentTrack=new JSONObject();instance=null;getSystemService(NotificationManager.class).cancel(88);super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
