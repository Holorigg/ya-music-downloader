package ru.holorigg.musicsync;

import android.content.*;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.util.Base64;
import android.util.Xml;
import org.json.*;
import org.xmlpull.v1.XmlPullParser;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

final class SyncEngine {
    static final AtomicBoolean running=new AtomicBoolean(false),stop=new AtomicBoolean(false);
    static volatile boolean automatic=false;static volatile long deadline=Long.MAX_VALUE;
    static volatile String status="Готово к синхронизации";static volatile int completed=0,total=0;
    static volatile String phase="catalog",currentTrack="";
    static volatile boolean userStopped=false;
    static volatile Store statusStore;
    final Context context;final Store store;final Net net;final Files files;
    SyncEngine(Context c,Store s){this(c,s,new Net(c,s));}
    SyncEngine(Context c,Store s,Net network){context=c;store=s;net=network;files=new Files(c,s);}
    static class Stopped extends IOException{Stopped(){super("Остановлено. Прогресс сохранён.");}}
    static void checkStop()throws Stopped{if(running.get()&&(stop.get()||System.currentTimeMillis()>deadline))throw new Stopped();}
    static void message(String text){status=text;Store s=statusStore;if(s!=null)s.prefs.edit().putString("status",text).apply();}
    static boolean begin(boolean auto){if(!running.compareAndSet(false,true))return false;stop.set(false);userStopped=false;automatic=auto;deadline=auto?System.currentTimeMillis()+8*60*1000:Long.MAX_VALUE;completed=0;total=0;phase="catalog";currentTrack="";return true;}
    void run()throws Exception{
        statusStore=store;
        int before=store.downloaded();
        try{
            File[] leftovers=context.getCacheDir().listFiles();if(leftovers!=null)for(File f:leftovers)if(f.isFile()&&f.getName().matches("(song|enhance|move|import)-.+\\.(raw|mp3)"))f.delete();
            String move=store.prefs.getString("move_target","");if(!move.isEmpty()){phase="move";message("Завершаю перенос музыки…");files.move(move);}
            String tree=store.prefs.getString("tree","");if(tree.isEmpty())throw new IOException("Сначала выбери папку сохранения");files.children(tree);catalog();
            for(JSONObject r:store.rows("pending_uri IS NOT NULL")){checkStop();files.recover(r);}
            for(JSONObject r:store.rows("status='downloaded' AND liked=1")){checkStop();if(!files.exists(r.optString("uri")))markMissingFile(r);}
            restoreUnavailable();
            for(int pass=1;pass<=3;pass++){
                checkStop();List<JSONObject> pending=store.rows("liked=1 AND status IN ('pending','failed')");if(pending.isEmpty())break;
                message("Скачивание: проход "+pass+", в очереди "+pending.size());process(pending,false);files.playlist(tree);
            }
            List<JSONObject> extras=store.rows("liked=1 AND status='downloaded' AND (cover IN ('pending','failed')"+(store.prefs.getBoolean("lyrics",true)?" OR lyrics IN ('pending','failed')":"")+")");
            if(!extras.isEmpty()){message("Обновляю обложки и тексты…");process(extras,true);}checkStop();files.playlist(tree);
            int done=store.downloaded(),left=store.rows("liked=1 AND status!='downloaded'").size();store.prefs.edit().putLong("last_sync",System.currentTimeMillis()).putInt("last_added",Math.max(0,done-before)).putInt("last_missing",left).putBoolean("needs_login",false).commit();phase="done";currentTrack="";message("Сохранено: "+done+". Не скачалось: "+left+".");
        }finally{statusStore=null;}
    }
    /** Queue a missing downloaded file only when current catalog metadata still permits a network download. */
    void markMissingFile(JSONObject row)throws Exception{
        checkStop();JSONObject metadata=Store.metadata(row);boolean available=metadata.optBoolean("available")||metadata.optBoolean("availableForPremiumUsers");
        ContentValues values=new ContentValues();values.put("status",available?"pending":"unavailable");values.putNull("uri");values.put("cover","pending");values.put("lyrics","pending");store.update(row.getString("id"),values);
    }
    /** Attempt local-only recovery for unavailable liked tracks; never enqueue them for network download here. */
    void restoreUnavailable()throws Exception{
        checkStop();String tree=store.prefs.getString("tree","");if(tree.isEmpty())return;
        for(JSONObject row:store.rows("liked=1 AND status='unavailable'")){
            checkStop();String id=row.getString("id");JSONObject current=store.row(id);if(current!=null)row=current;
            JSONObject metadata=Store.metadata(row);String name=Mp3.filename(Store.artist(metadata),metadata.optString("title"),Net.id(id));
            try{files.adoptExisting(row,metadata,tree,name);}catch(Stopped e){throw e;}catch(Exception e){ContentValues values=new ContentValues();values.put("error",Net.safe(e));store.update(id,values);}
        }
    }
    void catalog()throws Exception{
        phase="catalog";currentTrack="";total=0;completed=0;
        checkStop();message("Проверяю избранное…");JSONObject account=((JSONObject)net.api("/account/status",null)).getJSONObject("account");String uid=Net.id(account.getString("uid")),expected=store.expectedUid();if(!expected.isEmpty()&&!expected.equals(uid))throw new IOException("В токене другой аккаунт. Войди в прежний.");
        JSONObject liked=(JSONObject)net.api("/users/"+uid+"/likes/tracks",null);if(liked.has("library"))liked=liked.getJSONObject("library");JSONArray tracks=liked.getJSONArray("tracks");List<String> ids=new ArrayList<>();Set<String> seen=new HashSet<>();for(int n=0;n<tracks.length();n++){String id=Net.id(tracks.getJSONObject(n).getString("id"));if(seen.add(id))ids.add(id);}
        Map<String,JSONObject> metadata=new HashMap<>();for(int at=0;at<ids.size();at+=100){checkStop();List<String> batch=ids.subList(at,Math.min(at+100,ids.size()));JSONArray result=(JSONArray)net.api("/tracks",Net.fields("track-ids",String.join(",",batch)));for(int i=0;i<result.length();i++){JSONObject t=result.getJSONObject(i);metadata.put(t.getString("id"),t);}message("Проверено избранных: "+Math.min(at+100,ids.size())+" из "+ids.size());}checkStop();store.catalog(ids,metadata);store.prefs.edit().putString("uid",uid).putString("account_name",account.optString("displayName","Аккаунт Яндекса")).commit();
    }
    void process(List<JSONObject> rows,boolean enhance)throws Exception{
        phase=enhance?"metadata":"download";currentTrack="";total=rows.size();completed=0;ExecutorService pool=Executors.newFixedThreadPool(2);CompletionService<String> result=new ExecutorCompletionService<>(pool);Iterator<JSONObject> iterator=rows.iterator();int active=0;
        try{
            while(active<2&&iterator.hasNext()){submit(result,iterator.next(),enhance);active++;}
            while(active>0){checkStop();Future<String> future=result.poll(300,TimeUnit.MILLISECONDS);if(future==null)continue;active--;try{String title=future.get();completed++;message(completed+" из "+total+": "+title);}catch(ExecutionException e){Throwable cause=e.getCause();if(cause instanceof Exception)throw (Exception)cause;throw new IOException("Ошибка загрузки");}if(iterator.hasNext()){submit(result,iterator.next(),enhance);active++;}}
        }finally{pool.shutdown();if(stop.get()||System.currentTimeMillis()>deadline)stop.set(true);while(!pool.awaitTermination(1,TimeUnit.SECONDS)){} }
    }
    void submit(CompletionService<String> pool,JSONObject row,boolean enhance){pool.submit(()->{try{checkStop();currentTrack=Store.metadata(row).optString("title",row.getString("id"));if(enhance)enhance(row);else download(row);}catch(Net.LoginRequired e){stop.set(true);throw e;}catch(Stopped e){throw e;}catch(Exception e){if(enhance){ContentValues v=new ContentValues();v.put("error",Net.safe(e));store.update(row.getString("id"),v);}else store.fail(row.getString("id"),Net.safe(e));}return Store.metadata(row).optString("title",row.getString("id"));});}
    String direct(JSONObject info)throws Exception{
        String xml;HttpsURLConnection c=Net.publicGet(info.getString("downloadInfoUrl"));try{xml=new String(Net.read(c.getInputStream(),65536),StandardCharsets.UTF_8);}finally{c.disconnect();}
        Map<String,String> values=new HashMap<>();XmlPullParser p=Xml.newPullParser();p.setInput(new StringReader(xml));while(p.next()!=XmlPullParser.END_DOCUMENT)if(p.getEventType()==XmlPullParser.START_TAG&&Arrays.asList("host","path","ts","s").contains(p.getName())){String tag=p.getName();values.put(tag,p.nextText());}
        for(String key:new String[]{"host","path","ts","s"})if(!values.containsKey(key))throw new IOException("Яндекс не выдал полную ссылку MP3");String path=values.get("path");if(!path.startsWith("/"))throw new IOException("Некорректная ссылка MP3");String sign=Mp3.hex(MessageDigest.getInstance("MD5").digest(("XGRlBW9FXlekgbPrRHuSiA"+path.substring(1)+values.get("s")).getBytes(StandardCharsets.UTF_8)));return Net.allowed("https://"+values.get("host")+"/get-mp3/"+sign+"/"+values.get("ts")+path);
    }
    void download(JSONObject row)throws Exception{
        if(files.recover(row))return;JSONObject current=store.row(row.getString("id"));if(current!=null)row=current;checkStop();JSONObject t=Store.metadata(row);String tree=store.prefs.getString("tree","");String name=Mp3.filename(Store.artist(t),t.optString("title"),Net.id(row.getString("id")));if(files.adoptExisting(row,t,tree,name))return;if(t.optLong("durationMs")<=0)throw new IOException("Яндекс не выдал длительность для проверки полного MP3");JSONArray options=(JSONArray)net.api("/tracks/"+Net.id(row.getString("id"))+"/download-info",null);JSONObject best=null;for(int n=0;n<options.length();n++){JSONObject option=options.getJSONObject(n);if("mp3".equals(option.optString("codec"))&&option.has("preview")&&!option.getBoolean("preview")&&(best==null||option.optInt("bitrateInKbps")>best.optInt("bitrateInKbps")))best=option;}if(best==null)throw new IOException("Яндекс не выдал доступный полный MP3");
        if(context.getCacheDir().getUsableSpace()<256L*1024*1024)throw new IOException("Недостаточно места для временного файла");
        File raw=File.createTempFile("song-",".raw",context.getCacheDir()),tagged=File.createTempFile("song-",".mp3",context.getCacheDir());
        try{
            HttpsURLConnection c=Net.publicGet(direct(best));try(InputStream in=c.getInputStream();FileOutputStream out=new FileOutputStream(raw)){long expected=c.getContentLengthLong(),size=0;byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){checkStop();out.write(b,0,n);size+=n;}out.getFD().sync();if(size==0||(expected>=0&&size!=expected))throw new IOException("MP3 загружен не полностью");}finally{c.disconnect();}
            checkStop();Mp3.inspect(raw,t.optLong("durationMs"));tagAndPublish(row,t,raw,tagged,store.prefs.getString("tree",""),false);
        }finally{raw.delete();tagged.delete();}
    }
    byte[] cover(JSONObject t)throws Exception{
        String uri=t.optString("coverUri");if(uri.isEmpty())return null;String url=Net.allowed((uri.startsWith("https://")?uri:"https://"+uri).replace("%%","400x400"));String key=Mp3.hex(MessageDigest.getInstance("SHA-256").digest(url.getBytes(StandardCharsets.UTF_8)));File directory=new File(context.getFilesDir(),"covers");directory.mkdirs();File cache=new File(directory,key);
        synchronized(("cover:"+key).intern()){
            if(cache.isFile()){try(InputStream in=new FileInputStream(cache)){return Net.read(in,5*1024*1024);}}
            HttpsURLConnection c=Net.publicGet(url);byte[] bytes;try{bytes=Net.read(c.getInputStream(),5*1024*1024);}finally{c.disconnect();}
            String mime=coverMime(bytes);BitmapFactory.Options opts=new BitmapFactory.Options();opts.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(bytes,0,bytes.length,opts);if(opts.outWidth<1||opts.outWidth>4096||opts.outHeight<1||opts.outHeight>4096)throw new IOException("Некорректная обложка");try(FileOutputStream out=new FileOutputStream(cache)){out.write(bytes);out.getFD().sync();}return bytes;
        }
    }
    static String coverMime(byte[] b)throws IOException{if(b.length>3&&b[0]==(byte)255&&b[1]==(byte)216&&b[2]==(byte)255)return "image/jpeg";if(b.length>8&&b[0]==(byte)137&&b[1]=='P'&&b[2]=='N'&&b[3]=='G')return "image/png";throw new IOException("Неподдерживаемая обложка");}
    JSONObject lyrics(JSONObject t)throws Exception{
        if(!store.prefs.getBoolean("lyrics",true))return null;String id=Net.id(t.getString("id"));File dir=new File(context.getFilesDir(),"lyrics");dir.mkdirs();File cache=new File(dir,id.replace(':','_')+".json");if(cache.isFile()){try(InputStream in=new FileInputStream(cache)){return new JSONObject(new String(Net.read(in,2*1024*1024),StandardCharsets.UTF_8));}}
        JSONObject info=t.optJSONObject("lyricsInfo");String[] formats=info!=null&&info.optBoolean("hasAvailableSyncLyrics")?new String[]{"LRC","TEXT"}:new String[]{"TEXT"};
        for(String format:formats){checkStop();long stamp=System.currentTimeMillis()/1000;Mac mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec("p93jhgh689SBReK6ghtw62".getBytes(StandardCharsets.UTF_8),"HmacSHA256"));String sign=Base64.encodeToString(mac.doFinal((id.split(":")[0]+stamp).getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);JSONObject response;
            try{response=(JSONObject)net.api("/tracks/"+id+"/lyrics?"+Net.form(Net.fields("format",format,"timeStamp",Long.toString(stamp),"sign",sign)),null);}catch(Net.HttpError e){if(e.code==404)continue;throw e;}
            if(response==null||!response.has("downloadUrl"))continue;HttpsURLConnection c=Net.publicGet(response.getString("downloadUrl"));String text;try{text=new String(Net.read(c.getInputStream(),2*1024*1024),StandardCharsets.UTF_8).replace("\uFEFF","").replace("\r\n","\n").trim();}finally{c.disconnect();}
            if(text.isEmpty())continue;if(text.indexOf('\0')>=0||text.matches("(?is)^\\s*(<!doctype|<html|<script).*"))throw new IOException("Яндекс выдал страницу вместо текста");JSONObject data=new JSONObject().put("format",format).put("text",text);try(FileOutputStream out=new FileOutputStream(cache)){out.write(data.toString().getBytes(StandardCharsets.UTF_8));out.getFD().sync();}return data;
        }return null;
    }
    static String plain(JSONObject lyric){if(lyric==null)return null;String text=lyric.optString("text");if(!"LRC".equals(lyric.optString("format")))return text;return text.replaceAll("(?m)^\\[(?i:ar|al|ti|by|offset|length):[^\\]]*\\]\\s*","").replaceAll("\\[\\d+:\\d+(?:[.,]\\d+)?\\]","").trim();}
    void tagAndPublish(JSONObject row,JSONObject t,File raw,File tagged,String tree,boolean existing)throws Exception{
        byte[] image=null;JSONObject lyric=null;String coverStatus="unavailable",lyricStatus=store.prefs.getBoolean("lyrics",true)?"unavailable":"pending",warning=null;
        try{image=cover(t);if(image!=null)coverStatus="done";}catch(Exception e){coverStatus="failed";warning=Net.safe(e);}
        try{lyric=lyrics(t);if(lyric!=null)lyricStatus="done";}catch(Net.LoginRequired e){throw e;}catch(Stopped e){throw e;}catch(Exception e){lyricStatus="failed";warning=Net.safe(e);}
        checkStop();Map<String,String> tags=Net.fields("title",t.optString("title"),"artist",Store.artist(t),"album",Store.album(t).optString("title"),"year",Store.album(t).optString("year"));Mp3.tag(raw,tagged,tags,image,image!=null?coverMime(image):null,plain(lyric),t.optLong("durationMs"));String name=existing?row.getString("name"):Mp3.filename(Store.artist(t),t.optString("title"),row.getString("id"));
        if(existing){
            // Enhanced files use a distinct version first; commit it before
            // deleting the verified old file, so a process death loses no MP3.
            Uri old=Uri.parse(row.getString("uri"));if(!files.hash(old).equals(row.getString("sha")))throw new IOException("MP3 изменён после загрузки. Он сохранён без перезаписи.");
            String version=name.substring(0,name.length()-4)+"_meta.mp3";files.publish(row,tagged,tree,version,coverStatus,lyricStatus);
            if(files.hash(old).equals(row.getString("sha")))android.provider.DocumentsContract.deleteDocument(context.getContentResolver(),old);
            JSONObject fresh=store.row(row.getString("id"));Uri renamed=android.provider.DocumentsContract.renameDocument(context.getContentResolver(),Uri.parse(fresh.getString("uri")),name);
            if(renamed!=null){ContentValues v=new ContentValues();v.put("uri",renamed.toString());v.put("name",name);store.update(row.getString("id"),v);}else name=version;
        }else files.publish(row,tagged,tree,name,coverStatus,lyricStatus);
        if(lyric!=null){String stem=name.substring(0,name.length()-4);files.sidecar(tree,stem+".txt","text/plain",plain(lyric));if("LRC".equals(lyric.optString("format")))files.sidecar(tree,stem+".lrc","text/plain",lyric.getString("text"));}
        if(warning!=null){ContentValues v=new ContentValues();v.put("error",warning);store.update(row.getString("id"),v);}
    }
    void enhance(JSONObject row)throws Exception{
        File source=File.createTempFile("enhance-",".raw",context.getCacheDir()),tagged=File.createTempFile("enhance-",".mp3",context.getCacheDir());try{
            Uri uri=Uri.parse(row.getString("uri"));try(InputStream in=context.getContentResolver().openInputStream(uri);OutputStream out=new FileOutputStream(source)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){checkStop();out.write(b,0,n);}}
            if(!Mp3.hash(source).equals(row.getString("sha")))throw new IOException("MP3 изменён; он сохранён без перезаписи");tagAndPublish(row,Store.metadata(row),source,tagged,row.getString("tree"),true);
        }finally{source.delete();tagged.delete();}
    }
}
