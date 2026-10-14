package ru.holorigg.musicsync;

import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import org.robolectric.*;
import org.robolectric.annotation.*;
import java.io.*;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk=35)
@GraphicsMode(GraphicsMode.Mode.LEGACY)
public class ExistingFileChecks {
    private static final String AUTHORITY="ru.holorigg.musicsync.tests.documents";
    private Context context;private Store store;private TestDocuments provider;private String tree;

    public static class TestDocuments extends ContentProvider {
        static final class Document {final String id,name,mime;final int flags;final File file;Document(String i,String n,String m,int f,File p){id=i;name=n;mime=m;flags=f;file=p;}}
        final Map<String,Document> docs=new LinkedHashMap<>();final List<File> createdFiles=new ArrayList<>();int childQueries,opens;Runnable onSecondChildrenQuery,onSecondOpen;
        @Override public boolean onCreate(){return true;}
        void reset(){docs.clear();createdFiles.clear();childQueries=0;opens=0;onSecondChildrenQuery=null;onSecondOpen=null;}
        void add(Context c,String id,String name,byte[] bytes)throws Exception{File f=File.createTempFile("saf-fixture-",".mp3",c.getCacheDir());createdFiles.add(f);try(FileOutputStream out=new FileOutputStream(f)){out.write(bytes);}docs.put(id,new Document(id,name,"audio/mpeg",0,f));}
        @Override public Cursor query(Uri uri,String[] projection,String selection,String[] selectionArgs,String sortOrder){
            List<String> path=uri.getPathSegments();int document=path.indexOf("document");if(document<0)throw new IllegalArgumentException(uri.toString());String id=path.get(document+1);boolean children=path.contains("children");
            MatrixCursor result=new MatrixCursor(projection);
            if(children){childQueries++;if(childQueries==2&&onSecondChildrenQuery!=null)onSecondChildrenQuery.run();if("root".equals(id))for(Document d:docs.values())result.addRow(values(projection,d));}
            else if("root".equals(id))result.addRow(values(projection,new Document("root","Music",DocumentsContract.Document.MIME_TYPE_DIR,0,null)));
            else{Document d=docs.get(id);if(d!=null)result.addRow(values(projection,d));}
            return result;
        }
        private Object[] values(String[] projection,Document d){Object[] values=new Object[projection.length];for(int i=0;i<projection.length;i++)switch(projection[i]){
            case DocumentsContract.Document.COLUMN_DOCUMENT_ID:values[i]=d.id;break;
            case DocumentsContract.Document.COLUMN_DISPLAY_NAME:values[i]=d.name;break;
            case DocumentsContract.Document.COLUMN_MIME_TYPE:values[i]=d.mime;break;
            case DocumentsContract.Document.COLUMN_FLAGS:values[i]=d.flags;break;
            case DocumentsContract.Document.COLUMN_SIZE:values[i]=d.file==null?0:d.file.length();break;
            default:values[i]=null;
        }return values;}
        @Override public String getType(Uri uri){Document d=document(uri);return d==null?null:d.mime;}
        @Override public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException{Document d=document(uri);if(d==null||d.file==null)throw new FileNotFoundException(uri.toString());opens++;if(opens==2&&onSecondOpen!=null)onSecondOpen.run();return ParcelFileDescriptor.open(d.file,ParcelFileDescriptor.MODE_READ_ONLY);}
        private Document document(Uri uri){List<String> p=uri.getPathSegments();int i=p.indexOf("document");return i<0||i+1>=p.size()?null:docs.get(p.get(i+1));}
        @Override public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
        @Override public int delete(Uri uri,String where,String[] args){throw new UnsupportedOperationException();}
        @Override public int update(Uri uri,ContentValues values,String where,String[] args){throw new UnsupportedOperationException();}
    }

    private static final class NoNetwork extends Net {
        int requests;NoNetwork(Context c,Store s){super(c,s);}
        @Override Object api(String path,Map<String,String> body)throws Exception{requests++;throw new AssertionError("Network request during local recovery: "+path);}
    }
    @Before public void setUp()throws Exception{
        context=RuntimeEnvironment.getApplication();context.getSharedPreferences("settings",0).edit().clear().commit();context.deleteDatabase("music.db");store=new Store(context);
        provider=Robolectric.setupContentProvider(TestDocuments.class,AUTHORITY);provider.reset();tree=DocumentsContract.buildTreeDocumentUri(AUTHORITY,"root").toString();store.prefs.edit().putString("tree",tree).commit();SyncEngine.running.set(false);SyncEngine.stop.set(false);
    }
    @After public void tearDown(){SyncEngine.running.set(false);SyncEngine.stop.set(false);store.close();for(File f:provider.createdFiles)f.delete();}
    private JSONObject metadata(String id,String title,String artist,String album,long duration)throws Exception{return new JSONObject().put("id",id).put("title",title).put("available",true).put("durationMs",duration).put("artists",new JSONArray().put(new JSONObject().put("name",artist))).put("albums",new JSONArray().put(new JSONObject().put("title",album)));}
    private JSONObject seed(String id,String title,String artist,String album,long duration)throws Exception{JSONObject metadata=metadata(id,title,artist,album,duration);Map<String,JSONObject> all=new HashMap<>();all.put(id,metadata);store.catalog(Collections.singletonList(id),all);return store.row(id);}
    private JSONObject unavailableMetadata(String id,String title,String artist,String album,long duration)throws Exception{return metadata(id,title,artist,album,duration).put("available",false);}
    private long duration(int frames){return Math.round(frames*1152.0/44100*1000);}
    private byte[] tagged(String title,String artist,String album,int frames,boolean cover,boolean lyrics)throws Exception{
        File raw=File.createTempFile("raw-fixture-",".mp3",context.getCacheDir()),tagged=File.createTempFile("tagged-fixture-",".mp3",context.getCacheDir());
        try{
            try(FileOutputStream out=new FileOutputStream(raw)){byte[] frame=new byte[417];frame[0]=(byte)0xff;frame[1]=(byte)0xfb;frame[2]=(byte)0x90;frame[3]=0;for(int i=0;i<frames;i++)out.write(frame);}
            Map<String,String> values=new HashMap<>();values.put("title",title);values.put("artist",artist);values.put("album",album);
            Mp3.tag(raw,tagged,values,cover?new byte[]{1,2,3}:null,cover?"image/png":null,lyrics?"Synthetic lyric":null,duration(frames));return read(tagged);
        }finally{raw.delete();tagged.delete();}
    }
    private byte[] read(File file)throws Exception{try(InputStream in=new FileInputStream(file);ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1)out.write(b,0,n);return out.toByteArray();}}
    private String documentUri(String id){return DocumentsContract.buildDocumentUriUsingTree(Uri.parse(tree),id).toString();}
    private void runDownload(JSONObject row,NoNetwork network)throws Exception{new SyncEngine(context,store,network).download(row);}
    private void rejected(JSONObject row,NoNetwork network)throws Exception{try{runDownload(row,network);fail("Candidate must be refused");}catch(IOException expected){} }

    @Test public void adoptsMatchingFullMp3WithoutNetworkOrWritingIt()throws Exception{
        JSONObject row=seed("42","Тихий берег","Демо-артист","Альбом 01",duration(40));String name=Mp3.filename("Демо-артист","Тихий берег","42");byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,true,true);provider.add(context,"track-42",name,original);NoNetwork network=new NoNetwork(context,store);
        runDownload(row,network);JSONObject adopted=store.row("42");
        assertEquals(0,network.requests);assertEquals("downloaded",adopted.getString("status"));assertEquals(name,adopted.getString("name"));assertEquals("done",adopted.getString("cover"));assertEquals("done",adopted.getString("lyrics"));assertEquals(Mp3.hex(java.security.MessageDigest.getInstance("SHA-256").digest(original)),adopted.getString("sha"));assertArrayEquals(original,read(provider.docs.get("track-42").file));
    }
    @Test public void matchingKnownChecksumRestoresRememberedFileAfterMetadataChanges()throws Exception{
        JSONObject row=seed("49","Тихий берег","Демо-артист","Альбом 01",duration(40));String rememberedName=Mp3.filename("Демо-артист","Тихий берег","49");byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false);provider.add(context,"known-match",rememberedName,original);String rememberedUri=documentUri("known-match");ContentValues values=new ContentValues();values.put("sha",Mp3.hex(java.security.MessageDigest.getInstance("SHA-256").digest(original)));values.put("uri",rememberedUri);values.put("tree",tree);values.put("name",rememberedName);store.update("49",values);
        JSONObject changed=metadata("49","Новое название","Новый артист","Новый альбом",0);Map<String,JSONObject> all=new HashMap<>();all.put("49",changed);store.catalog(Collections.singletonList("49"),all);NoNetwork network=new NoNetwork(context,store);
        runDownload(store.row("49"),network);JSONObject adopted=store.row("49");assertEquals(0,network.requests);assertEquals("downloaded",adopted.getString("status"));assertEquals(rememberedName,adopted.getString("name"));assertEquals(rememberedUri,adopted.getString("uri"));assertEquals("pending",adopted.getString("cover"));assertEquals("pending",adopted.getString("lyrics"));assertArrayEquals(original,read(provider.docs.get("known-match").file));
    }
    @Test public void mismatchedId3TagsAreRefusedAndPreserved()throws Exception{
        JSONObject row=seed("43","Тихий берег","Демо-артист","Альбом 01",duration(40));String name=Mp3.filename("Демо-артист","Тихий берег","43");byte[] original=tagged("Тихий берег","Другой артист","Альбом 01",40,false,false);provider.add(context,"foreign",name,original);NoNetwork network=new NoNetwork(context,store);
        rejected(row,network);assertEquals(0,network.requests);assertEquals("pending",store.row("43").getString("status"));assertArrayEquals(original,read(provider.docs.get("foreign").file));
    }
    @Test public void wrongDurationAndTruncatedFramesAreRefusedAndPreserved()throws Exception{
        String title="Тихий берег",artist="Демо-артист",album="Альбом 01";JSONObject row=seed("44",title,artist,album,10000);String name=Mp3.filename(artist,title,"44");byte[] wrongDuration=tagged(title,artist,album,200,false,false);provider.add(context,"wrong-duration",name,wrongDuration);NoNetwork network=new NoNetwork(context,store);
        rejected(row,network);assertArrayEquals(wrongDuration,read(provider.docs.get("wrong-duration").file));provider.docs.clear();
        row=seed("45",title,artist,album,duration(40));name=Mp3.filename(artist,title,"45");byte[] full=tagged(title,artist,album,40,false,false),truncated=Arrays.copyOf(full,full.length-1);provider.add(context,"truncated",name,truncated);
        rejected(row,network);assertEquals(0,network.requests);assertArrayEquals(truncated,read(provider.docs.get("truncated").file));
    }
    @Test public void knownChecksumMismatchCannotBeRelearnedFromMatchingTags()throws Exception{
        JSONObject row=seed("46","Тихий берег","Демо-артист","Альбом 01",duration(40));byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false);String name=Mp3.filename("Демо-артист","Тихий берег","46");provider.add(context,"changed-known",name,original);byte[] prior=tagged("Тихий берег","Демо-артист","Альбом 01",41,false,false);ContentValues values=new ContentValues();values.put("sha",Mp3.hex(java.security.MessageDigest.getInstance("SHA-256").digest(prior)));values.put("uri",documentUri("changed-known"));values.put("tree",tree);values.put("name",name);store.update("46",values);NoNetwork network=new NoNetwork(context,store);
        rejected(store.row("46"),network);assertEquals(0,network.requests);assertArrayEquals(original,read(provider.docs.get("changed-known").file));
    }
    @Test public void changeDuringVerificationIsRefused()throws Exception{
        JSONObject row=seed("47","Тихий берег","Демо-артист","Альбом 01",duration(40));String name=Mp3.filename("Демо-артист","Тихий берег","47");byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false),changed=tagged("Тихий берег","Демо-артист","Альбом 01",41,false,false);provider.add(context,"race",name,original);provider.onSecondOpen=()->{try(FileOutputStream out=new FileOutputStream(provider.docs.get("race").file)){out.write(changed);}catch(Exception e){throw new RuntimeException(e);}};NoNetwork network=new NoNetwork(context,store);
        rejected(row,network);assertEquals(0,network.requests);assertArrayEquals(changed,read(provider.docs.get("race").file));assertEquals("pending",store.row("47").getString("status"));
    }
    @Test public void stopAfterChecksumRecheckPreventsCommit()throws Exception{
        JSONObject row=seed("50","Тихий берег","Демо-артист","Альбом 01",duration(40));String name=Mp3.filename("Демо-артист","Тихий берег","50");byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false);provider.add(context,"paused",name,original);provider.onSecondOpen=()->SyncEngine.stop.set(true);NoNetwork network=new NoNetwork(context,store);SyncEngine.running.set(true);
        try{rejected(row,network);}finally{SyncEngine.running.set(false);SyncEngine.stop.set(false);}
        assertEquals(0,network.requests);assertEquals("pending",store.row("50").getString("status"));assertArrayEquals(original,read(provider.docs.get("paused").file));
    }
    @Test public void unavailableTracksUseOnlyLocalRecoveryAndStayUnavailableWithoutProof()throws Exception{
        List<String> ids=Arrays.asList("61","62","63");Map<String,JSONObject> all=new LinkedHashMap<>();all.put("61",unavailableMetadata("61","Тихий берег","Демо-артист","Альбом 01",duration(40)));all.put("62",unavailableMetadata("62","Синяя дорога","Другой артист","Альбом 02",duration(40)));all.put("63",unavailableMetadata("63","Поздний поезд","Третий артист","Альбом 03",duration(40)));store.catalog(ids,all);
        String acceptedName=Mp3.filename("Демо-артист","Тихий берег","61"),foreignName=Mp3.filename("Другой артист","Синяя дорога","62");byte[] accepted=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false),foreign=tagged("Синяя дорога","Чужой артист","Альбом 02",40,false,false);provider.add(context,"unavailable-accepted",acceptedName,accepted);provider.add(context,"unavailable-foreign",foreignName,foreign);NoNetwork network=new NoNetwork(context,store);
        new SyncEngine(context,store,network).restoreUnavailable();
        assertEquals(0,network.requests);assertEquals("downloaded",store.row("61").getString("status"));assertEquals("unavailable",store.row("62").getString("status"));assertEquals("unavailable",store.row("63").getString("status"));assertArrayEquals(accepted,read(provider.docs.get("unavailable-accepted").file));assertArrayEquals(foreign,read(provider.docs.get("unavailable-foreign").file));
    }
    @Test public void unavailableRecoveryStopsImmediately()throws Exception{
        List<String> ids=Collections.singletonList("64");Map<String,JSONObject> all=new HashMap<>();all.put("64",unavailableMetadata("64","Тихий берег","Демо-артист","Альбом 01",duration(40)));store.catalog(ids,all);String name=Mp3.filename("Демо-артист","Тихий берег","64");byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false);provider.add(context,"unavailable-stopped",name,original);SyncEngine.running.set(true);SyncEngine.stop.set(true);NoNetwork network=new NoNetwork(context,store);
        try{new SyncEngine(context,store,network).restoreUnavailable();fail("Stopped recovery must exit before examining tracks");}catch(SyncEngine.Stopped expected){}finally{SyncEngine.running.set(false);SyncEngine.stop.set(false);}
        assertEquals(0,network.requests);assertEquals("unavailable",store.row("64").getString("status"));assertArrayEquals(original,read(provider.docs.get("unavailable-stopped").file));
    }
    @Test public void missingPreviouslyDownloadedUnavailableFileStaysOutOfNetworkQueue()throws Exception{
        JSONObject row=seed("65","Тихий берег","Демо-артист","Альбом 01",duration(40));String name=Mp3.filename("Демо-артист","Тихий берег","65");byte[] previous=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false);ContentValues owned=new ContentValues();owned.put("status","downloaded");owned.put("sha",Mp3.hex(java.security.MessageDigest.getInstance("SHA-256").digest(previous)));owned.put("uri",documentUri("removed"));owned.put("tree",tree);owned.put("name",name);store.update("65",owned);
        Map<String,JSONObject> all=new HashMap<>();all.put("65",unavailableMetadata("65","Тихий берег","Демо-артист","Альбом 01",duration(40)));store.catalog(Collections.singletonList("65"),all);NoNetwork network=new NoNetwork(context,store);SyncEngine engine=new SyncEngine(context,store,network);engine.markMissingFile(store.row("65"));
        assertEquals("unavailable",store.row("65").getString("status"));engine.restoreUnavailable();assertEquals("unavailable",store.row("65").getString("status"));assertEquals(0,network.requests);
    }
    @Test public void duplicateNamesAreRefusedAndAFileAppearingBeforePublishIsNotOverwritten()throws Exception{
        JSONObject row=seed("48","Тихий берег","Демо-артист","Альбом 01",duration(40));String name=Mp3.filename("Демо-артист","Тихий берег","48");byte[] original=tagged("Тихий берег","Демо-артист","Альбом 01",40,false,false);provider.add(context,"first",name,original);provider.add(context,"second",name,original);NoNetwork network=new NoNetwork(context,store);
        rejected(row,network);assertEquals(0,network.requests);assertArrayEquals(original,read(provider.docs.get("first").file));assertArrayEquals(original,read(provider.docs.get("second").file));provider.docs.clear();provider.childQueries=0;
        Files files=new Files(context,store);assertFalse(files.adoptExisting(row,Store.metadata(row),tree,name));provider.add(context,"appeared",name,original);File source=File.createTempFile("publish-fixture-",".mp3",context.getCacheDir());try(FileOutputStream out=new FileOutputStream(source)){out.write(new byte[]{1,2,3});}
        try{files.publish(row,source,tree,name,"pending","pending");fail("Publish must retain the collision guard");}catch(IOException expected){}finally{source.delete();}
        assertArrayEquals(original,read(provider.docs.get("appeared").file));assertEquals(1,provider.docs.size());
    }
}
