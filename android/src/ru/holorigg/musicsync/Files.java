package ru.holorigg.musicsync;

import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

final class Files {
    final Context context;final Store store;
    Files(Context c,Store s){context=c;store=s;}
    Uri root(String tree){Uri t=Uri.parse(tree);return DocumentsContract.buildDocumentUriUsingTree(t,DocumentsContract.getTreeDocumentId(t));}
    Map<String,Uri> children(String tree)throws Exception{Map<String,Uri> r=new HashMap<>();Uri t=Uri.parse(tree),children=DocumentsContract.buildChildDocumentsUriUsingTree(t,DocumentsContract.getTreeDocumentId(t));try(Cursor c=context.getContentResolver().query(children,new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_DISPLAY_NAME},null,null,null)){if(c==null)throw new IOException("Папка недоступна");while(c.moveToNext())r.put(c.getString(1),DocumentsContract.buildDocumentUriUsingTree(t,c.getString(0)));}return r;}
    String display(String tree){try(Cursor c=context.getContentResolver().query(root(tree),new String[]{DocumentsContract.Document.COLUMN_DISPLAY_NAME},null,null,null)){if(c!=null&&c.moveToFirst())return c.getString(0);}catch(Exception ignored){}return "Выбранная папка";}
    boolean exists(String uri){if(uri==null||uri.isEmpty())return false;try(Cursor c=context.getContentResolver().query(Uri.parse(uri),new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID},null,null,null)){return c!=null&&c.moveToFirst();}catch(Exception e){return false;}}
    String hash(Uri uri)throws Exception{InputStream in=context.getContentResolver().openInputStream(uri);if(in==null)throw new IOException("Файл недоступен");try(InputStream f=in){return Mp3.hash(f);}}
    Uri create(String tree,String mime,String name)throws Exception{Uri result=DocumentsContract.createDocument(context.getContentResolver(),root(tree),mime,name);if(result==null)throw new IOException("Папка не поддерживает создание файлов");return result;}
    void write(Uri uri,InputStream source)throws Exception{try(InputStream in=source;OutputStream out=context.getContentResolver().openOutputStream(uri,"wt")){if(out==null)throw new IOException("Не удалось открыть файл для записи");byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){SyncEngine.checkStop();out.write(b,0,n);}out.flush();}}
    synchronized void publish(JSONObject row,File source,String tree,String name,String cover,String lyrics)throws Exception{
        String sha=Mp3.hash(source);Map<String,Uri> children=children(tree);if(children.containsKey(name))throw new IOException("В папке уже есть такой файл. Он сохранён без перезаписи.");
        Uri part=create(tree,"application/octet-stream",name+".part");ContentValues pending=new ContentValues();pending.put("pending_uri",part.toString());pending.put("pending_sha",sha);pending.put("pending_size",source.length());pending.put("pending_tree",tree);pending.put("pending_name",name);pending.put("pending_cover",cover);pending.put("pending_lyrics",lyrics);store.update(row.getString("id"),pending);
        write(part,new FileInputStream(source));if(!hash(part).equals(sha))throw new IOException("Файл не прошёл проверку после записи");
        Uri target=DocumentsContract.renameDocument(context.getContentResolver(),part,name);if(target==null)throw new IOException("Папка не поддерживает переименование. Выбери локальную папку Music.");
        pending.put("pending_uri",target.toString());store.update(row.getString("id"),pending);if(!hash(target).equals(sha))throw new IOException("Файл не прошёл проверку после переименования");commit(row.getString("id"),target,tree,name,sha,source.length(),cover,lyrics);
    }
    synchronized void commit(String id,Uri uri,String tree,String name,String sha,long size,String cover,String lyrics){ContentValues v=new ContentValues();v.put("status","downloaded");v.put("uri",uri.toString());v.put("tree",tree);v.put("name",name);v.put("sha",sha);v.put("size",size);v.put("cover",cover);v.put("lyrics",lyrics);v.putNull("error");for(String k:new String[]{"pending_uri","pending_sha","pending_size","pending_tree","pending_name","pending_cover","pending_lyrics"})v.putNull(k);store.update(id,v);}
    synchronized boolean recover(JSONObject row)throws Exception{
        String pending=row.optString("pending_uri");if(pending.isEmpty())return false;String tree=row.getString("pending_tree"),name=row.getString("pending_name"),sha=row.getString("pending_sha");Uri uri=Uri.parse(pending);
        Uri finalUri=children(tree).get(name);
        if(finalUri!=null&&hash(finalUri).equals(sha)){commit(row.getString("id"),finalUri,tree,name,sha,row.getLong("pending_size"),row.optString("pending_cover"),row.optString("pending_lyrics"));return true;}
        if(exists(pending)){
            if(hash(uri).equals(sha)){if(finalUri!=null)throw new IOException("Файл с таким именем уже есть — не перезаписываю");Uri renamed=DocumentsContract.renameDocument(context.getContentResolver(),uri,name);if(renamed==null)throw new IOException("Не удалось завершить сохранение MP3");commit(row.getString("id"),renamed,tree,name,sha,row.getLong("pending_size"),row.optString("pending_cover"),row.optString("pending_lyrics"));return true;}
            // Only our journalled incomplete file is removed. Other files stay.
            DocumentsContract.deleteDocument(context.getContentResolver(),uri);
        }
        ContentValues v=new ContentValues();for(String k:new String[]{"pending_uri","pending_sha","pending_size","pending_tree","pending_name","pending_cover","pending_lyrics"})v.putNull(k);store.update(row.getString("id"),v);return false;
    }
    void sidecar(String tree,String name,String mime,String text)throws Exception{Map<String,Uri> files=children(tree);byte[] content=(text+"\n").getBytes(StandardCharsets.UTF_8);if(files.containsKey(name)){try(InputStream in=context.getContentResolver().openInputStream(files.get(name))){if(!Arrays.equals(Net.read(in,2*1024*1024),content))throw new IOException("Рядом уже есть другой текст — он сохранён");}return;}write(create(tree,mime,name),new ByteArrayInputStream(content));}
    void playlist(String tree)throws Exception{StringBuilder text=new StringBuilder("#EXTM3U\n");for(JSONObject r:store.rows("status='downloaded' AND liked=1"))if(tree.equals(r.optString("tree")))text.append(r.optString("name").replace("\n","").replace("\r","")).append('\n');String name="Мне_нравится.m3u8";Map<String,Uri> files=children(tree);String remembered=store.prefs.getString("playlist:"+tree,"");Uri uri=files.get(name);if(uri!=null&&!uri.toString().equals(remembered))return;if(uri==null){uri=create(tree,"audio/x-mpegurl",name);store.prefs.edit().putString("playlist:"+tree,uri.toString()).commit();}write(uri,new ByteArrayInputStream(text.toString().getBytes(StandardCharsets.UTF_8)));}
    void move(String target)throws Exception{
        JSONObject journal=new JSONObject(store.prefs.getString("move_journal","{}"));
        for(JSONObject row:store.rows("status='downloaded'")){
            SyncEngine.checkStop();String id=row.getString("id");JSONObject original=journal.optJSONObject(id);
            if(original==null){if(row.optString("tree").equals(target))continue;original=new JSONObject().put("uri",row.getString("uri")).put("tree",row.getString("tree")).put("name",row.getString("name")).put("sha",row.getString("sha"));journal.put(id,original);store.prefs.edit().putString("move_journal",journal.toString()).commit();}
            String old=original.getString("tree"),name=original.getString("name"),originalSha=original.getString("sha");Uri source=Uri.parse(original.getString("uri"));
            if(!row.optString("pending_uri").isEmpty()){recover(row);row=store.row(id);}
            File temp=File.createTempFile("move-",".mp3",context.getCacheDir());try{
                if(!row.optString("tree").equals(target)){
                    if(!exists(source.toString())||!hash(source).equals(originalSha))throw new IOException("Один из MP3 изменён. Перенос остановлен, файл сохранён.");
                    try(InputStream in=context.getContentResolver().openInputStream(source);OutputStream out=new FileOutputStream(temp)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){SyncEngine.checkStop();out.write(b,0,n);}}
                    publish(row,temp,target,name,row.optString("cover"),row.optString("lyrics"));
                }
                for(String ext:new String[]{".txt",".lrc"}){String side=name.substring(0,name.length()-4)+ext;Uri existing=children(old).get(side);if(existing!=null){String text;String before=hash(existing);try(InputStream in=context.getContentResolver().openInputStream(existing)){text=new String(Net.read(in,2*1024*1024),StandardCharsets.UTF_8).trim();}sidecar(target,side,"text/plain",text);if(hash(existing).equals(before))DocumentsContract.deleteDocument(context.getContentResolver(),existing);}}
                if(exists(source.toString())){if(!hash(source).equals(originalSha))throw new IOException("Исходный MP3 изменён после копирования. Он сохранён.");DocumentsContract.deleteDocument(context.getContentResolver(),source);}
                journal.remove(id);store.prefs.edit().putString("move_journal",journal.toString()).commit();
                SyncEngine.message("Переношу: "+Store.metadata(row).optString("title"));
            }finally{temp.delete();}
        }
        store.prefs.edit().putString("tree",target).remove("move_target").remove("move_journal").commit();playlist(target);
    }
}
