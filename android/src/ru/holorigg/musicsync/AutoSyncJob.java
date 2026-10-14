package ru.holorigg.musicsync;
import android.app.job.*;
import android.os.*;
public final class AutoSyncJob extends JobService {
    private volatile boolean owns=false,wasStopped=false;private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable progress=new Runnable(){public void run(){if(owns){SyncNotifications.progress(AutoSyncJob.this);handler.postDelayed(this,2500);}}};
    @Override public boolean onStartJob(JobParameters parameters){
        Store store=new Store(this);
        if(!store.prefs.getBoolean("auto",false)||store.prefs.getBoolean("needs_login",false)||store.prefs.getString("tree","").isEmpty()||!SyncEngine.begin(true)){store.close();return false;}
        owns=true;wasStopped=false;SyncNotifications.channels(this);handler.post(progress);
        new Thread(()->{
            boolean retry=false;String outcome="done";
            try{new SyncEngine(getApplicationContext(),store).run();}
            catch(Net.LoginRequired e){outcome="login";store.prefs.edit().putBoolean("needs_login",true).commit();SyncEngine.message(Net.safe(e));}
            catch(SyncEngine.Stopped e){outcome="stopped";SyncEngine.message("Фоновая проверка приостановлена. Прогресс сохранён.");retry=store.prefs.getBoolean("auto",false)&&!SyncEngine.userStopped;}
            catch(Exception e){outcome="error";SyncEngine.message(Net.safe(e));}
            finally{store.prefs.edit().putString("status",SyncEngine.status).putString("last_outcome",outcome).putLong("last_result_at",System.currentTimeMillis()).commit();}
            final boolean again=retry;final String result=outcome;
            handler.post(()->{owns=false;SyncEngine.running.set(false);handler.removeCallbacks(progress);SyncNotifications.finish(this,store,result,true);store.close();if(!wasStopped)jobFinished(parameters,again);});
        },"automatic-music-sync").start();return true;
    }
    @Override public boolean onStopJob(JobParameters parameters){wasStopped=true;if(owns&&SyncEngine.automatic)SyncEngine.stop.set(true);handler.removeCallbacks(progress);return !SyncEngine.userStopped;}
}
