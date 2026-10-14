package ru.holorigg.musicsync;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import org.json.*;
import java.util.*;

final class Store extends SQLiteOpenHelper {
    static final java.util.concurrent.atomic.AtomicLong revision=new java.util.concurrent.atomic.AtomicLong();
    final SharedPreferences prefs;
    Store(Context c){super(c.getApplicationContext(),"music.db",null,2);prefs=c.getSharedPreferences("settings",Context.MODE_PRIVATE);setWriteAheadLoggingEnabled(true);}
    @Override public void onCreate(SQLiteDatabase d){d.execSQL("CREATE TABLE tracks(id TEXT PRIMARY KEY,position INTEGER,liked INTEGER DEFAULT 1,archive_hidden INTEGER NOT NULL DEFAULT 0,metadata TEXT,status TEXT DEFAULT 'pending',uri TEXT,tree TEXT,name TEXT,sha TEXT,size INTEGER,error TEXT,cover TEXT DEFAULT 'pending',lyrics TEXT DEFAULT 'pending',pending_uri TEXT,pending_sha TEXT,pending_size INTEGER,pending_tree TEXT,pending_name TEXT,pending_cover TEXT,pending_lyrics TEXT)");}
    @Override public void onUpgrade(SQLiteDatabase d,int oldVersion,int newVersion){if(oldVersion<2)d.execSQL("ALTER TABLE tracks ADD COLUMN archive_hidden INTEGER NOT NULL DEFAULT 0");}
    List<JSONObject> visibleRows(){return rows("liked=1 OR archive_hidden=0");}
    // Keep file ownership and checksums even when a song is removed from the visible archive.
    synchronized List<String> hideArchive(List<String> requested){
        List<String> changed=new ArrayList<>();SQLiteDatabase d=getWritableDatabase();d.beginTransaction();try{
            List<String> ids=requested;
            if(ids==null){ids=new ArrayList<>();try(Cursor c=d.query("tracks",new String[]{"id"},"liked=0 AND archive_hidden=0",null,null,null,null)){while(c.moveToNext())ids.add(c.getString(0));}}
            ContentValues values=new ContentValues();values.put("archive_hidden",1);
            for(String id:ids)if(d.update("tracks",values,"id=? AND liked=0 AND archive_hidden=0",new String[]{id})>0)changed.add(id);
            d.setTransactionSuccessful();
        }finally{d.endTransaction();}if(!changed.isEmpty())revision.incrementAndGet();return changed;
    }
    synchronized void restoreArchive(List<String> ids){SQLiteDatabase d=getWritableDatabase();d.beginTransaction();try{ContentValues v=new ContentValues();v.put("archive_hidden",0);for(String id:ids)d.update("tracks",v,"id=? AND liked=0",new String[]{id});d.setTransactionSuccessful();}finally{d.endTransaction();}revision.incrementAndGet();}
    synchronized List<JSONObject> rows(String selection){List<JSONObject> result=new ArrayList<>();try(Cursor c=getReadableDatabase().query("tracks",null,selection,null,null,null,"liked DESC,position")){while(c.moveToNext()){JSONObject r=new JSONObject();for(int n=0;n<c.getColumnCount();n++){try{if(!c.isNull(n))r.put(c.getColumnName(n),c.getString(n));}catch(JSONException ignored){}}result.add(r);}}return result;}
    JSONObject row(String id){List<JSONObject> r=rows("id='"+Net.id(id)+"'");return r.isEmpty()?null:r.get(0);}
    synchronized void update(String id,ContentValues values){getWritableDatabase().update("tracks",values,"id=?",new String[]{id});revision.incrementAndGet();}
    synchronized void fail(String id,String message){ContentValues v=new ContentValues();v.put("status","failed");v.put("error",message);update(id,v);}
    synchronized void catalog(List<String> ids,Map<String,JSONObject> metadata)throws Exception{
        SQLiteDatabase d=getWritableDatabase();d.beginTransaction();try{
            d.execSQL("UPDATE tracks SET liked=0");for(int i=0;i<ids.size();i++){
                String id=ids.get(i);JSONObject t=metadata.get(id);if(t==null)t=metadata.get(id.split(":")[0]);if(t==null)t=new JSONObject().put("id",id).put("title",id).put("available",false);
                boolean available=t.optBoolean("available")||t.optBoolean("availableForPremiumUsers");
                d.execSQL("INSERT OR IGNORE INTO tracks(id,status) VALUES(?,?)",new Object[]{id,available?"pending":"unavailable"});
                d.execSQL("UPDATE tracks SET position=?,liked=1,archive_hidden=0,metadata=?,status=CASE WHEN status='downloaded' THEN status WHEN ?=0 THEN 'unavailable' WHEN status='unavailable' THEN 'pending' ELSE status END WHERE id=?",new Object[]{i,t.toString(),available?1:0,id});
            }d.setTransactionSuccessful();
        }finally{d.endTransaction();}revision.incrementAndGet();
    }
    int downloaded(){return rows("status='downloaded'").size();}
    String expectedUid(){return downloaded()>0?prefs.getString("uid",""):"";}
    static JSONObject metadata(JSONObject row)throws JSONException{return new JSONObject(row.optString("metadata","{}"));}
    static String artist(JSONObject t){JSONArray a=t.optJSONArray("artists");StringBuilder b=new StringBuilder();if(a!=null)for(int n=0;n<a.length();n++){JSONObject artist=a.optJSONObject(n);if(artist==null)continue;if(b.length()>0)b.append(", ");b.append(artist.optString("name"));}return b.toString();}
    static JSONObject album(JSONObject t){JSONArray a=t.optJSONArray("albums");JSONObject album=a==null?null:a.optJSONObject(0);return album==null?new JSONObject():album;}
}
