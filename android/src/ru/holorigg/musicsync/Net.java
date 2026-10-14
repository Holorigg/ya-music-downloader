package ru.holorigg.musicsync;

import android.content.*;
import android.security.keystore.*;
import android.util.Base64;
import org.json.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;

class Net {
    static final String API="https://api.music.yandex.net",CLIENT="YandexMusicAndroid/24023621";
    // Public client parameters already used in the reviewed desktop implementation.
    static final String CLIENT_ID="23cabbbdc6cd418abb4b39c32c41195d",CLIENT_SECRET="53bc75238f0c4d08a118e51fe9203300";
    static final Object AUTH_LOCK=new Object();
    final Context context;final Store store;
    Net(Context c,Store s){context=c==null?null:c.getApplicationContext();store=s;}
    static class LoginRequired extends IOException{LoginRequired(){super("Нужно войти заново: открой вкладку «Аккаунт».");}}
    static class HttpError extends IOException{final int code;HttpError(int c){super("Яндекс: HTTP "+c);code=c;}}
    static String id(String value){if(!value.matches("[0-9]+(?::[0-9]+)?"))throw new IllegalArgumentException("Неожиданный ID песни");return value;}
    static String form(Map<String,String> data)throws Exception{StringBuilder b=new StringBuilder();for(Map.Entry<String,String> e:data.entrySet()){if(b.length()>0)b.append('&');b.append(URLEncoder.encode(e.getKey(),"UTF-8")).append('=').append(URLEncoder.encode(e.getValue(),"UTF-8"));}return b.toString();}
    static Map<String,String> fields(String... pairs){Map<String,String> m=new LinkedHashMap<>();for(int n=0;n<pairs.length;n+=2)m.put(pairs[n],pairs[n+1]);return m;}
    static byte[] read(InputStream in,int limit)throws IOException{try(InputStream stream=in;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] buffer=new byte[65536];int n;while((n=stream.read(buffer))!=-1){if(out.size()+n>limit)throw new IOException("Ответ сервера слишком большой");out.write(buffer,0,n);}return out.toByteArray();}}
    static HttpsURLConnection connection(String url,String token,Map<String,String> data)throws Exception{
        URL u=new URL(url);if(!u.getProtocol().equals("https"))throw new IOException("Требуется HTTPS");
        HttpsURLConnection c=(HttpsURLConnection)u.openConnection();c.setConnectTimeout(10000);c.setReadTimeout(15000);c.setInstanceFollowRedirects(false);c.setRequestProperty("Accept-Encoding","identity");
        if(token!=null){c.setRequestProperty("Authorization","OAuth "+token);c.setRequestProperty("X-Yandex-Music-Client",CLIENT);}
        if(data!=null){c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/x-www-form-urlencoded");byte[] body=form(data).getBytes(StandardCharsets.UTF_8);c.setFixedLengthStreamingMode(body.length);try(OutputStream out=c.getOutputStream()){out.write(body);}}
        return c;
    }
    static JSONObject oauth(String path,Map<String,String> data)throws Exception{
        HttpsURLConnection c=connection("https://oauth.yandex.ru/"+path,null,data);try{int code=c.getResponseCode();if(code!=200&&code!=400)throw new HttpError(code);return new JSONObject(new String(read(code==200?c.getInputStream():c.getErrorStream(),1024*1024),StandardCharsets.UTF_8));}finally{c.disconnect();}
    }
    JSONObject oauthRequest(String path,Map<String,String> data)throws Exception{return oauth(path,data);}
    static SecretKey key()throws Exception{KeyStore keys=KeyStore.getInstance("AndroidKeyStore");keys.load(null);if(keys.containsAlias("MusicOAuth"))return (SecretKey)keys.getKey("MusicOAuth",null);KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");generator.init(new KeyGenParameterSpec.Builder("MusicOAuth",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());return generator.generateKey();}
    JSONObject auth()throws Exception{
        String value=store.prefs.getString("auth","");if(value.isEmpty())throw new LoginRequired();
        try{byte[] data=Base64.decode(value,Base64.NO_WRAP);int length=data[0]&255;if(length<12||length>16||data.length<=length+1)throw new GeneralSecurityException();Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Arrays.copyOfRange(data,1,length+1)));return new JSONObject(new String(c.doFinal(Arrays.copyOfRange(data,length+1,data.length)),StandardCharsets.UTF_8));}catch(Exception e){throw new LoginRequired();}
    }
    void storeAuth(JSONObject auth)throws Exception{Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());byte[] iv=cipher.getIV(),encrypted=cipher.doFinal(auth.toString().getBytes(StandardCharsets.UTF_8));ByteArrayOutputStream b=new ByteArrayOutputStream();b.write(iv.length);b.write(iv);b.write(encrypted);if(!store.prefs.edit().putString("auth",Base64.encodeToString(b.toByteArray(),Base64.NO_WRAP)).putBoolean("needs_login",false).commit())throw new IOException("Не удалось сохранить вход");}
    JSONObject account(String token)throws Exception{
        if(token==null||token.isEmpty()||token.length()>4096||token.matches("(?s).*\\s.*"))throw new IOException("Вставь только токен, без пробелов и слова OAuth");
        HttpsURLConnection c=connection(API+"/account/status",token,null);try{int code=c.getResponseCode();if(code==401||code==403)throw new LoginRequired();if(code!=200)throw new HttpError(code);JSONObject a=new JSONObject(new String(read(c.getInputStream(),1024*1024),StandardCharsets.UTF_8)).getJSONObject("result").getJSONObject("account");String uid=id(a.getString("uid")),previous=store.expectedUid();if(!previous.isEmpty()&&!previous.equals(uid))throw new IOException("Это другой аккаунт. Войди в прежний — сохранённая музыка осталась на месте.");return a;}finally{c.disconnect();}
    }
    void saveToken(String token)throws Exception{synchronized(AUTH_LOCK){JSONObject account=account(token);storeAuth(new JSONObject().put("access_token",token).put("account",account));store.prefs.edit().putString("account_name",account.optString("displayName","Аккаунт Яндекса")).apply();}}
    String token()throws Exception{return auth().getString("access_token");}
    String refresh(String old)throws Exception{synchronized(AUTH_LOCK){JSONObject a=auth();if(!a.getString("access_token").equals(old))return a.getString("access_token");if(!a.has("refresh_token"))throw new LoginRequired();JSONObject r=oauthRequest("token",fields("grant_type","refresh_token","refresh_token",a.getString("refresh_token"),"client_id",CLIENT_ID,"client_secret",CLIENT_SECRET));if(!r.has("access_token"))throw new LoginRequired();JSONObject account=account(r.getString("access_token"));Iterator<String> keys=r.keys();while(keys.hasNext()){String k=keys.next();a.put(k,r.get(k));}a.put("account",account);storeAuth(a);return a.getString("access_token");}}
    Object api(String path,Map<String,String> body)throws Exception{
        String token=token();boolean renewed=false;
        for(int n=0;n<4;n++){
            HttpsURLConnection c=null;try{c=connection(API+path,token,body);int code=c.getResponseCode();if(code==401){if(renewed)throw new LoginRequired();token=refresh(token);renewed=true;continue;}if(code==403&&path.equals("/account/status"))throw new LoginRequired();if((code==429||code>=500)&&n<2){Thread.sleep((n+1)*2000L);continue;}if(code!=200)throw new HttpError(code);JSONObject data=new JSONObject(new String(read(c.getInputStream(),16*1024*1024),StandardCharsets.UTF_8));if(data.has("error"))throw new IOException("Яндекс не выдал запрошенные данные");return data.get("result");}
            catch(LoginRequired|HttpError e){throw e;}catch(IOException e){if(n>=2)throw new IOException("Сетевая ошибка: "+e.getClass().getSimpleName());Thread.sleep(1000);}finally{if(c!=null)c.disconnect();}
        }throw new LoginRequired();
    }
    static String allowed(String value)throws Exception{
        URI u=new URI(value);String host=u.getHost();if(!"https".equals(u.getScheme())||u.getRawUserInfo()!=null||(u.getPort()!=-1&&u.getPort()!=443)||host==null)throw new IOException("Неожиданный сервер файла");host=host.toLowerCase(Locale.ROOT);if(!(host.equals("yandex.net")||host.endsWith(".yandex.net")||host.equals("yandex.ru")||host.endsWith(".yandex.ru")))throw new IOException("Неожиданный сервер файла");return value;
    }
    static HttpsURLConnection publicGet(String url)throws Exception{
        for(int n=0;n<6;n++){allowed(url);HttpsURLConnection c=connection(url,null,null);int code=c.getResponseCode();if(code==301||code==302||code==303||code==307||code==308){String next=c.getHeaderField("Location");c.disconnect();if(next==null)throw new IOException("Пустое перенаправление");url=new URI(url).resolve(next).toString();continue;}if(code!=200){c.disconnect();throw new HttpError(code);}return c;}throw new IOException("Слишком много перенаправлений");
    }
    JSONObject requestCode()throws Exception{JSONObject r=oauthRequest("device/code",fields("client_id",CLIENT_ID,"device_id",UUID.randomUUID().toString(),"device_name","My Music on Android"));String url=r.getString("verification_url");URI u=new URI(url);if(!"https".equals(u.getScheme())||u.getRawUserInfo()!=null||(u.getPort()!=-1&&u.getPort()!=443)||!("oauth.yandex.ru".equals(u.getHost())||"oauth.yandex.com".equals(u.getHost())||("ya.ru".equals(u.getHost())&&"/device".equals(u.getPath()))))throw new IOException("Неожиданный адрес входа");r.put("expires_at",System.currentTimeMillis()+r.getLong("expires_in")*1000);store.prefs.edit().putString("device",r.toString()).commit();return r;}
    String poll()throws Exception{
        String stored=store.prefs.getString("device","");if(stored.isEmpty())return "idle";JSONObject d=new JSONObject(stored);if(System.currentTimeMillis()>=d.getLong("expires_at"))return "expired";
        JSONObject r=oauthRequest("token",fields("grant_type","device_code","code",d.getString("device_code"),"client_id",CLIENT_ID,"client_secret",CLIENT_SECRET));String error=r.optString("error");if(error.equals("authorization_pending"))return "waiting";if(error.equals("slow_down"))return "slow_down";if(!r.has("access_token"))return "expired";
        synchronized(AUTH_LOCK){if(!stored.equals(store.prefs.getString("device","")))return "idle";JSONObject a=account(r.getString("access_token"));r.put("account",a);storeAuth(r);store.prefs.edit().remove("device").putString("account_name",a.optString("displayName","Аккаунт Яндекса")).commit();}return "authorized";
    }
    static String safe(Exception e){if(e instanceof LoginRequired)return e.getMessage();if(e instanceof HttpError)return e.getMessage();if(e instanceof SecurityException)return "Нет доступа к папке: выбери её заново в настройках";String text=e.getMessage();if(text==null||text.contains("https://")||text.contains("access_token")||text.contains("OAuth "))return "Ошибка: "+e.getClass().getSimpleName();return text.length()>400?text.substring(0,400):text;}
}
