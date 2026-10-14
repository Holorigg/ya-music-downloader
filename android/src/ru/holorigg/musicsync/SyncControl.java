package ru.holorigg.musicsync;
import android.content.*;
public final class SyncControl extends BroadcastReceiver {
    static final String STOP="ru.holorigg.musicsync.STOP";
    static void stop(){SyncEngine.userStopped=true;SyncEngine.stop.set(true);}
    @Override public void onReceive(Context context,Intent intent){if(STOP.equals(intent.getAction()))stop();}
}
