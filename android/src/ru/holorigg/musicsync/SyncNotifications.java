package ru.holorigg.musicsync;
import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.drawable.Icon;

final class SyncNotifications {
    static final int PROGRESS=71,RESULT=72;
    static void channels(Context c){NotificationManager manager=c.getSystemService(NotificationManager.class);NotificationChannel sync=new NotificationChannel("music_sync","Скачивание музыки",NotificationManager.IMPORTANCE_LOW);sync.setDescription("Прогресс и остановка скачивания");sync.setShowBadge(false);manager.createNotificationChannel(sync);NotificationChannel result=new NotificationChannel("music_updates","Результаты синхронизации",NotificationManager.IMPORTANCE_DEFAULT);result.setDescription("Новые треки и ошибки");manager.createNotificationChannel(result);}
    static String phaseTitle(){String phase=SyncEngine.phase;return phase.equals("metadata")?"Обложки и тексты":phase.equals("download")?"Скачивание музыки":phase.equals("move")?"Перенос музыки":"Проверка избранного";}
    static PendingIntent open(Context c,int tab){return PendingIntent.getActivity(c,tab,new Intent(c,MainActivity.class).putExtra("tab",tab).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    static Notification ongoing(Context c){
        String detail=SyncEngine.currentTrack.isEmpty()?SyncEngine.status:SyncEngine.currentTrack;
        PendingIntent stop=PendingIntent.getBroadcast(c,71,new Intent(c,SyncControl.class).setAction(SyncControl.STOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b=new Notification.Builder(c,"music_sync").setSmallIcon(R.drawable.ic_notification).setColor(Color.rgb(118,90,19)).setContentTitle(SyncEngine.stop.get()?"Останавливаем…":phaseTitle()).setContentText(detail).setContentIntent(open(c,0)).setOnlyAlertOnce(true).setOngoing(true).setShowWhen(false).setCategory(Notification.CATEGORY_PROGRESS).setVisibility(Notification.VISIBILITY_PRIVATE).setProgress(Math.max(1,SyncEngine.total),SyncEngine.completed,SyncEngine.total==0);
        if(SyncEngine.total>0)b.setSubText(SyncEngine.completed+" / "+SyncEngine.total);
        b.addAction(new Notification.Action.Builder(Icon.createWithResource(c,R.drawable.ic_stop),"Остановить",stop).build());return b.build();
    }
    static void progress(Context c){try{c.getSystemService(NotificationManager.class).notify(PROGRESS,ongoing(c));}catch(SecurityException ignored){}}
    static void finish(Context c,Store store,String outcome,boolean automatic){
        NotificationManager manager=c.getSystemService(NotificationManager.class);manager.cancel(PROGRESS);
        if(!store.prefs.getBoolean("notify_results",true))return;
        boolean login=outcome.equals("login"),failed=outcome.equals("error"),stopped=outcome.equals("stopped");int added=store.prefs.getInt("last_added",0),missing=store.prefs.getInt("last_missing",0);String title,detail;
        if(login){title="Нужен вход в Яндекс";detail="Открой аккаунт и войди заново";}
        else if(failed){title="Синхронизация не завершена";detail="Открой приложение, чтобы повторить";}
        else if(stopped){if(automatic)return;title="Скачивание остановлено";detail="Прогресс сохранён";}
        else if(missing>0){title="Не скачалось "+Ui.tracks(missing);detail=added>0?"Добавлено: "+Ui.tracks(added):"Остальные песни сохранены";}
        else{if(automatic&&added==0)return;title=added>0?"Музыка обновлена":"Всё синхронизировано";detail=added>0?"Добавлено: "+Ui.tracks(added):"Новых треков нет";}
        String signature=outcome+":"+missing+":"+added;
        if(automatic&&(login||failed||missing>0)&&signature.equals(store.prefs.getString("notified_result","")))return;
        store.prefs.edit().putString("notified_result",signature).apply();
        Notification.Builder b=new Notification.Builder(c,"music_updates").setSmallIcon(R.drawable.ic_notification).setColor(Color.rgb(118,90,19)).setContentTitle(title).setContentText(detail).setContentIntent(open(c,login?2:0)).setAutoCancel(true).setCategory(login||failed?Notification.CATEGORY_ERROR:Notification.CATEGORY_STATUS).setVisibility(Notification.VISIBILITY_PRIVATE);
        b.addAction(new Notification.Action.Builder(Icon.createWithResource(c,login?R.drawable.ic_account:R.drawable.ic_library),login?"Войти":"Открыть",open(c,login?2:0)).build());try{manager.notify(RESULT,b.build());}catch(SecurityException ignored){}
    }
}
