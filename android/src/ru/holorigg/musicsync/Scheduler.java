package ru.holorigg.musicsync;
import android.app.job.*;
import android.content.*;
import android.net.*;
import android.os.Build;
final class Scheduler {
    static final int ID=20071;
    static void apply(Context context,Store store){
        JobScheduler scheduler=context.getSystemService(JobScheduler.class);
        if(!store.prefs.getBoolean("auto",false)){scheduler.cancel(ID);return;}
        long interval=store.prefs.getInt("hours",6)*3600000L;int network=store.prefs.getBoolean("wifi",false)?JobInfo.NETWORK_TYPE_UNMETERED:JobInfo.NETWORK_TYPE_ANY;
        boolean wifi=store.prefs.getBoolean("wifi",false);
        JobInfo previous=scheduler.getPendingJob(ID);if(previous!=null&&previous.getIntervalMillis()==interval&&store.prefs.getBoolean("scheduled_wifi",false)==wifi)return;
        JobInfo.Builder builder=new JobInfo.Builder(ID,new ComponentName(context,AutoSyncJob.class)).setPeriodic(interval,Math.max(15*60*1000,interval/6)).setPersisted(true).setBackoffCriteria(60*1000,JobInfo.BACKOFF_POLICY_EXPONENTIAL);
        if(wifi&&Build.VERSION.SDK_INT>=28)builder.setRequiredNetwork(new NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build());else builder.setRequiredNetworkType(network);
        if(scheduler.schedule(builder.build())!=JobScheduler.RESULT_SUCCESS){store.prefs.edit().putBoolean("auto",false).apply();SyncEngine.message("Android не смог включить фоновую проверку. Попробуй снова.");}else store.prefs.edit().putBoolean("scheduled_wifi",wifi).apply();
    }
}
