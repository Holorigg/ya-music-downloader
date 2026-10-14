package ru.holorigg.musicsync;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
public final class SyncService extends Service {
    static final String STOP=SyncControl.STOP;
    private final Handler handler=new Handler(Looper.getMainLooper());private volatile boolean owns=false;
    private Store store;private PowerManager.WakeLock wake;private String lastNotice="";
    private final Runnable progress=new Runnable(){public void run(){if(owns){String key=SyncEngine.phase+":"+SyncEngine.currentTrack+":"+SyncEngine.completed+":"+SyncEngine.total+":"+SyncEngine.stop.get();if(!key.equals(lastNotice)){lastNotice=key;SyncNotifications.progress(SyncService.this);}handler.postDelayed(this,1500);}}};
    @Override public void onCreate(){super.onCreate();SyncNotifications.channels(this);}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null&&STOP.equals(intent.getAction())){SyncControl.stop();if(!owns)stopSelf();return START_NOT_STICKY;}
        if(!SyncEngine.begin(false)){if(!owns)stopSelf();return START_NOT_STICKY;}
        owns=true;store=new Store(this);SyncEngine.message("Проверяем избранное…");
        if(Build.VERSION.SDK_INT>=29)startForeground(SyncNotifications.PROGRESS,SyncNotifications.ongoing(this),ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);else startForeground(SyncNotifications.PROGRESS,SyncNotifications.ongoing(this));
        wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"MusicSync:download");wake.acquire(6*60*60*1000L);handler.post(progress);
        new Thread(()->{
            String outcome="done";
            try{new SyncEngine(getApplicationContext(),store).run();}
            catch(Net.LoginRequired e){outcome="login";store.prefs.edit().putBoolean("needs_login",true).commit();SyncEngine.message(Net.safe(e));}
            catch(SyncEngine.Stopped e){outcome="stopped";SyncEngine.message("Остановлено. Прогресс сохранён.");}
            catch(Exception e){outcome="error";SyncEngine.message(Net.safe(e));}
            finally{String result=outcome;store.prefs.edit().putString("status",SyncEngine.status).putString("last_outcome",result).putLong("last_result_at",System.currentTimeMillis()).commit();
                handler.post(()->{owns=false;SyncEngine.running.set(false);handler.removeCallbacks(progress);if(wake!=null&&wake.isHeld())wake.release();stopForeground(STOP_FOREGROUND_REMOVE);SyncNotifications.finish(this,store,result,false);store.close();stopSelf();});}
        },"manual-music-sync").start();return START_NOT_STICKY;
    }
    @Override public void onTimeout(int startId,int fgsType){SyncEngine.stop.set(true);stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();}
    @Override public void onDestroy(){if(owns)SyncEngine.stop.set(true);handler.removeCallbacks(progress);if(wake!=null&&wake.isHeld())wake.release();super.onDestroy();}
    @Override public IBinder onBind(Intent intent){return null;}
}
