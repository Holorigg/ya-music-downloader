package ru.holorigg.musicsync;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Pure Java MPEG frame validation and ID3 writing. Compressed audio is copied. */
public final class Mp3 {
    public static final class Info {
        public long start,end,durationMs,frames;
    }
    public static final class Tags {
        public final Map<String,String> text=new HashMap<>();
        public boolean cover,lyrics;
    }
    private static int synchsafe(byte[] b,int at) throws IOException {
        int n=0;for(int i=at;i<at+4;i++){if((b[i]&128)!=0)throw new IOException("Некорректный ID3");n=(n<<7)|(b[i]&127);}return n;
    }
    public static Info inspect(File file,long expectedMs) throws Exception {
        Info info=new Info();
        try(RandomAccessFile f=new RandomAccessFile(file,"r")) {
            long length=f.length();if(length<8)throw new IOException("Пустой или неполный MP3");
            byte[] head=new byte[10];f.readFully(head);
            if(head[0]=='I'&&head[1]=='D'&&head[2]=='3')info.start=10L+synchsafe(head,6)+(((head[3]&255)==4&&(head[5]&16)!=0)?10:0);
            info.end=length;
            if(length>=128){f.seek(length-128);if(f.readByte()=='T'&&f.readByte()=='A'&&f.readByte()=='G')info.end-=128;}
            if(info.end>=32){f.seek(info.end-32);byte[] footer=new byte[8];f.readFully(footer);if(Arrays.equals(footer,"APETAGEX".getBytes(StandardCharsets.US_ASCII))){int v=Integer.reverseBytes(f.readInt());long size=Integer.toUnsignedLong(Integer.reverseBytes(f.readInt()));if(v>=1000&&size>=32&&size<info.end-info.start)info.end-=size;}}
            if(info.start>=info.end)throw new IOException("В MP3 нет аудиоданных");
            long at=info.start;double seconds=0;int[] v1={0,32,40,48,56,64,80,96,112,128,160,192,224,256,320};int[] v2={0,8,16,24,32,40,48,56,64,80,96,112,128,144,160};int[] rates={44100,48000,32000};
            while(at<info.end){
                if(info.end-at<4)throw new IOException("Оборван последний кадр MP3");
                f.seek(at);int h=f.readInt();int version=(h>>>19)&3,layer=(h>>>17)&3,bit=(h>>>12)&15,rate=(h>>>10)&3;
                if((h&0xffe00000)!=0xffe00000||version==1||layer!=1||bit==0||bit==15||rate==3)throw new IOException("Некорректный или оборванный MP3");
                int hz=rates[rate]/(version==3?1:version==2?2:4),kbps=(version==3?v1:v2)[bit];
                int size=(version==3?144000:72000)*kbps/hz+((h>>>9)&1);
                if(size<4||at+size>info.end)throw new IOException("Оборван последний кадр MP3");
                seconds+=(version==3?1152.0:576.0)/hz;at+=size;info.frames++;
            }
            info.durationMs=Math.round(seconds*1000);
            if(info.frames==0||(expectedMs>0&&Math.abs(info.durationMs-expectedMs)>Math.max(2500,expectedMs*.015)))throw new IOException("MP3 не прошёл проверку полной длительности");
        }
        return info;
    }
    /** Read only plain, uncompressed ID3v2.3/v2.4 frames written by this app. */
    public static Tags readTags(File file)throws Exception{
        Tags tags=new Tags();
        try(RandomAccessFile in=new RandomAccessFile(file,"r")){
            if(in.length()<10)throw new IOException("В MP3 нет ID3-тегов приложения");
            byte[] header=new byte[10];in.readFully(header);
            int version=header[3]&255,flags=header[5]&255;
            if(header[0]!='I'||header[1]!='D'||header[2]!='3'||(version!=3&&version!=4)||flags!=0)throw new IOException("Неподдерживаемый формат ID3");
            long end=10L+synchsafe(header,6);if(end>in.length())throw new IOException("Оборван заголовок ID3");
            while(in.getFilePointer()+10<=end){
                byte[] idBytes=new byte[4];in.readFully(idBytes);String id=new String(idBytes,StandardCharsets.US_ASCII);
                if(id.equals("\u0000\u0000\u0000\u0000"))break;
                if(!id.matches("[A-Z0-9]{4}"))throw new IOException("Некорректный кадр ID3");
                byte[] sizeBytes=new byte[4];in.readFully(sizeBytes);int size=version==4?synchsafe(sizeBytes,0):((sizeBytes[0]&255)<<24)|((sizeBytes[1]&255)<<16)|((sizeBytes[2]&255)<<8)|(sizeBytes[3]&255);
                int frameFlags=in.readUnsignedShort();long frameEnd=in.getFilePointer()+size;if(size<0||frameEnd>end||frameFlags!=0)throw new IOException("Некорректный кадр ID3");
                if(id.equals("TIT2")||id.equals("TPE1")||id.equals("TALB")){
                    if(size<2||size>1024*1024||tags.text.containsKey(id))throw new IOException("Некорректные текстовые теги MP3");
                    byte[] value=new byte[size];in.readFully(value);tags.text.put(id,decodeText(value));
                }else if(id.equals("APIC"))tags.cover=true;
                else if(id.equals("USLT"))tags.lyrics=true;
                in.seek(frameEnd);
            }
        }
        return tags;
    }
    private static String decodeText(byte[] frame)throws Exception{
        int encoding=frame[0]&255;String value;
        if(encoding==0)value=new String(frame,1,frame.length-1,StandardCharsets.ISO_8859_1);
        else if(encoding==1)value=new String(frame,1,frame.length-1,StandardCharsets.UTF_16);
        else if(encoding==2)value=new String(frame,1,frame.length-1,StandardCharsets.UTF_16BE);
        else if(encoding==3)value=new String(frame,1,frame.length-1,StandardCharsets.UTF_8);
        else throw new IOException("Неизвестная кодировка ID3");
        while(value.endsWith("\u0000"))value=value.substring(0,value.length()-1);
        if(value.indexOf('\u0000')>=0)throw new IOException("Несколько значений в теге ID3");
        return value;
    }
    private static byte[] text(String s){byte[] utf=s.replace("\u0000","").getBytes(StandardCharsets.UTF_16);byte[] b=new byte[utf.length+1];b[0]=1;System.arraycopy(utf,0,b,1,utf.length);return b;}
    private static void frame(DataOutputStream out,String id,byte[] data)throws IOException{out.write(id.getBytes(StandardCharsets.US_ASCII));out.writeInt(data.length);out.writeShort(0);out.write(data);}
    private static byte[] savedFrame(File source,String desired)throws Exception{
        try(RandomAccessFile in=new RandomAccessFile(source,"r")){byte[] header=new byte[10];in.readFully(header);if(header[0]!='I'||header[1]!='D'||header[2]!='3'||(header[3]!=3&&header[3]!=4)||header[5]!=0)return null;long end=10L+synchsafe(header,6);
            while(in.getFilePointer()+10<=end){byte[] id=new byte[4];in.readFully(id);String name=new String(id,StandardCharsets.US_ASCII);if(!name.matches("[A-Z0-9]{4}"))return null;byte[] length=new byte[4];in.readFully(length);int size=header[3]==4?synchsafe(length,0):((length[0]&255)<<24)|((length[1]&255)<<16)|((length[2]&255)<<8)|(length[3]&255);int flags=in.readUnsignedShort();if(size<0||in.getFilePointer()+size>end)return null;if(name.equals(desired)&&flags==0&&size<=8*1024*1024){byte[] b=new byte[size];in.readFully(b);return b;}in.seek(in.getFilePointer()+size);}
        }return null;
    }
    public static void tag(File raw,File result,Map<String,String> tags,byte[] image,String imageMime,String lyrics,long duration)throws Exception{
        Info original=inspect(raw,duration);ByteArrayOutputStream payload=new ByteArrayOutputStream();DataOutputStream frames=new DataOutputStream(payload);
        for(String[] pair:new String[][]{{"TIT2","title"},{"TPE1","artist"},{"TALB","album"},{"TYER","year"}}){String value=tags.get(pair[1]);if(value!=null&&!value.isEmpty())frame(frames,pair[0],text(value));}
        if(image!=null){ByteArrayOutputStream b=new ByteArrayOutputStream();b.write(0);b.write(imageMime.getBytes(StandardCharsets.US_ASCII));b.write(0);b.write(3);b.write(0);b.write(image);frame(frames,"APIC",b.toByteArray());}else{byte[] old=savedFrame(raw,"APIC");if(old!=null)frame(frames,"APIC",old);}
        if(lyrics!=null&&!lyrics.isEmpty()){ByteArrayOutputStream b=new ByteArrayOutputStream();b.write(1);b.write("und".getBytes(StandardCharsets.US_ASCII));b.write("YandexLyrics".getBytes(StandardCharsets.UTF_16));b.write(0);b.write(0);b.write(lyrics.getBytes(StandardCharsets.UTF_16));frame(frames,"USLT",b.toByteArray());}else{byte[] old=savedFrame(raw,"USLT");if(old!=null)frame(frames,"USLT",old);}
        byte[] body=payload.toByteArray();if(body.length>=0x10000000)throw new IOException("Теги слишком большие");
        try(FileOutputStream out=new FileOutputStream(result);RandomAccessFile in=new RandomAccessFile(raw,"r")){
            out.write(new byte[]{'I','D','3',3,0,0,(byte)((body.length>>>21)&127),(byte)((body.length>>>14)&127),(byte)((body.length>>>7)&127),(byte)(body.length&127)});out.write(body);in.seek(original.start);byte[] buffer=new byte[65536];long remaining=original.end-original.start;
            while(remaining>0){int n=in.read(buffer,0,(int)Math.min(remaining,buffer.length));if(n<0)throw new EOFException();out.write(buffer,0,n);remaining-=n;}out.getFD().sync();
        }
        Info tagged=inspect(result,duration);if(!audioHash(raw,original).equals(audioHash(result,tagged)))throw new IOException("Аудиоданные изменились при добавлении тегов");
    }
    public static String audioHash(File file,Info info)throws Exception{
        MessageDigest digest=MessageDigest.getInstance("SHA-256");try(RandomAccessFile in=new RandomAccessFile(file,"r")){in.seek(info.start);long left=info.end-info.start;byte[] b=new byte[65536];while(left>0){int n=in.read(b,0,(int)Math.min(left,b.length));if(n<0)throw new EOFException();digest.update(b,0,n);left-=n;}}return hex(digest.digest());
    }
    public static String hash(InputStream in)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)d.update(b,0,n);return hex(d.digest());}
    public static String hash(File file)throws Exception{try(InputStream in=new FileInputStream(file)){return hash(in);}}
    public static String hex(byte[] b){StringBuilder s=new StringBuilder();for(byte v:b)s.append(String.format(Locale.ROOT,"%02x",v&255));return s.toString();}
    public static String filename(String artist,String title,String id){String s=(artist+" - "+title).replaceAll("[\\x00-\\x1f<>:\"/\\\\|?*]","_").trim();if(s.length()>110)s=s.substring(0,110);return s+"__"+id.replace(':','_')+".mp3";}
}
