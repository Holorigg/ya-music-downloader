package ru.holorigg.musicsync;

import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.*;
import android.text.TextUtils;
import android.util.LruCache;
import android.view.*;
import android.widget.*;
import androidx.core.content.ContextCompat;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;
import androidx.appcompat.widget.AppCompatImageView;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.lang.ref.WeakReference;
import java.util.concurrent.*;

final class Ui {
    static int dp(Context c,float value){return Math.round(value*c.getResources().getDisplayMetrics().density);}
    static int color(Context c,int resource){
        int attr=0;
        if(resource==R.color.primary)attr=androidx.appcompat.R.attr.colorPrimary;
        else if(resource==R.color.on_primary)attr=com.google.android.material.R.attr.colorOnPrimary;
        else if(resource==R.color.primary_container)attr=com.google.android.material.R.attr.colorPrimaryContainer;
        else if(resource==R.color.on_primary_container)attr=com.google.android.material.R.attr.colorOnPrimaryContainer;
        else if(resource==R.color.secondary)attr=com.google.android.material.R.attr.colorSecondary;
        else if(resource==R.color.on_secondary)attr=com.google.android.material.R.attr.colorOnSecondary;
        else if(resource==R.color.secondary_container)attr=com.google.android.material.R.attr.colorSecondaryContainer;
        else if(resource==R.color.on_secondary_container)attr=com.google.android.material.R.attr.colorOnSecondaryContainer;
        else if(resource==R.color.surface)attr=com.google.android.material.R.attr.colorSurface;
        else if(resource==R.color.surface_low)attr=com.google.android.material.R.attr.colorSurfaceContainerLow;
        else if(resource==R.color.surface_container)attr=com.google.android.material.R.attr.colorSurfaceContainer;
        else if(resource==R.color.surface_high)attr=com.google.android.material.R.attr.colorSurfaceContainerHigh;
        else if(resource==R.color.on_surface)attr=com.google.android.material.R.attr.colorOnSurface;
        else if(resource==R.color.on_surface_variant)attr=com.google.android.material.R.attr.colorOnSurfaceVariant;
        else if(resource==R.color.outline)attr=com.google.android.material.R.attr.colorOutline;
        else if(resource==R.color.outline_variant)attr=com.google.android.material.R.attr.colorOutlineVariant;
        else if(resource==R.color.error)attr=androidx.appcompat.R.attr.colorError;
        else if(resource==R.color.on_error)attr=com.google.android.material.R.attr.colorOnError;
        else if(resource==R.color.error_container)attr=com.google.android.material.R.attr.colorErrorContainer;
        else if(resource==R.color.on_error_container)attr=com.google.android.material.R.attr.colorOnErrorContainer;
        else if(resource==R.color.success)attr=com.google.android.material.R.attr.colorTertiary;
        int fallback=ContextCompat.getColor(c,resource);
        return attr==0?fallback:com.google.android.material.color.MaterialColors.getColor(c,attr,fallback);
    }
    static TextView text(Context c,String value,int sp,int color,boolean medium){
        TextView t=new TextView(c);t.setText(value);t.setTextSize(sp);t.setTextColor(Ui.color(c,color));
        t.setFontFeatureSettings("kern");t.setIncludeFontPadding(false);
        t.setTypeface(Typeface.create(medium?"sans-serif-medium":"sans-serif",Typeface.NORMAL));return t;
    }
    static MaterialButton button(Context c,String title,int icon,boolean filled){
        int style=filled?com.google.android.material.R.attr.materialButtonStyle:com.google.android.material.R.attr.materialButtonOutlinedStyle;
        MaterialButton b=new MaterialButton(c,null,style);b.setText(title);b.setAllCaps(false);b.setTextSize(14);
        b.setMinHeight(dp(c,48));b.setMinimumHeight(dp(c,48));b.setInsetTop(0);b.setInsetBottom(0);b.setCornerRadius(dp(c,24));
        if(icon!=0){b.setIconResource(icon);b.setIconSize(dp(c,20));b.setIconPadding(dp(c,8));b.setIconGravity(MaterialButton.ICON_GRAVITY_TEXT_START);}
        return b;
    }
    static MaterialButton iconButton(Context c,int icon,String description,boolean prominent){
        MaterialButton b=button(c,"",icon,true);b.setContentDescription(description);b.setTooltipText(description);
        b.setMinWidth(0);b.setMinimumWidth(0);b.setPadding(0,0,0,0);b.setIconPadding(0);
        b.setIconGravity(MaterialButton.ICON_GRAVITY_TEXT_START);b.setIconSize(dp(c,24));
        b.setBackgroundTintList(ColorStateList.valueOf(color(c,prominent?R.color.primary_container:R.color.surface_low)));
        b.setIconTint(ColorStateList.valueOf(color(c,prominent?R.color.on_primary_container:R.color.on_surface_variant)));
        b.setLayoutParams(new LinearLayout.LayoutParams(dp(c,48),dp(c,48)));return b;
    }
    static LinearLayout column(Context c){LinearLayout l=new LinearLayout(c);l.setOrientation(LinearLayout.VERTICAL);return l;}
    static LinearLayout row(Context c){LinearLayout l=new LinearLayout(c);l.setOrientation(LinearLayout.HORIZONTAL);l.setGravity(Gravity.CENTER_VERTICAL);return l;}
    static MaterialCardView card(Context c){
        MaterialCardView card=new MaterialCardView(c);card.setRadius(dp(c,20));card.setCardElevation(0);
        card.setStrokeWidth(0);card.setCardBackgroundColor(color(c,R.color.surface_low));return card;
    }
    static final class ArtworkView extends AppCompatImageView {
        private final float radius;private final Path clip=new Path();
        ArtworkView(Context c,int radius){super(c);this.radius=dp(c,radius);}
        @Override protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);clip.reset();clip.addRoundRect(0,0,w,h,radius,radius,Path.Direction.CW);}
        @Override public void draw(Canvas canvas){int save=canvas.save();canvas.clipPath(clip);super.draw(canvas);canvas.restoreToCount(save);}
    }
    static ArtworkView art(Context c,int size,int radius){
        ArtworkView view=new ArtworkView(c,radius);view.setScaleType(ImageView.ScaleType.CENTER_CROP);
        view.setLayoutParams(new LinearLayout.LayoutParams(dp(c,size),dp(c,size)));view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);return view;
    }
    static String plural(int n,String one,String few,String many){int a=Math.abs(n)%100,b=a%10;return n+" "+(a>=11&&a<=14?many:b==1?one:b>=2&&b<=4?few:many);}
    static String tracks(int n){return plural(n,"трек","трека","треков");}
    static String initials(String name){String[] words=name.trim().split("\\s+");if(words.length==0||words[0].isEmpty())return "Я";return (words[0].substring(0,1)+(words.length>1?words[words.length-1].substring(0,1):"")).toUpperCase(java.util.Locale.ROOT);}
    static void ellipsis(TextView t,int lines){t.setMaxLines(lines);t.setEllipsize(TextUtils.TruncateAt.END);}
    static File coverFile(Context c,JSONObject track){
        try{String raw=track.optString("coverUri");if(raw.isEmpty())return null;String url=(raw.startsWith("https://")?raw:"https://"+raw).replace("%%","400x400");String hash=Mp3.hex(MessageDigest.getInstance("SHA-256").digest(url.getBytes(StandardCharsets.UTF_8)));return new File(new File(c.getFilesDir(),"covers"),hash);}catch(Exception e){return null;}
    }
    static Bitmap decodeCover(File file,int size){
        BitmapFactory.Options options=new BitmapFactory.Options();options.inJustDecodeBounds=true;BitmapFactory.decodeFile(file.getPath(),options);
        if(options.outWidth<1||options.outHeight<1||options.outWidth>4096||options.outHeight>4096)return null;
        options.inSampleSize=1;while(options.outWidth/(options.inSampleSize*2)>=size&&options.outHeight/(options.inSampleSize*2)>=size)options.inSampleSize*=2;
        options.inJustDecodeBounds=false;options.inPreferredConfig=Bitmap.Config.RGB_565;return BitmapFactory.decodeFile(file.getPath(),options);
    }
    static final class Covers {
        private final ExecutorService pool=Executors.newFixedThreadPool(2);
        private final Handler main=new Handler(Looper.getMainLooper());
        private final LruCache<String,Bitmap> cache=new LruCache<String,Bitmap>(12*1024*1024){protected int sizeOf(String key,Bitmap value){return value.getAllocationByteCount();}};
        private boolean closed;
        void bind(ArtworkView view,JSONObject track){
            String id=track.optString("id",track.optString("title"));
            Context c=view.getContext();int wanted=Math.max(dp(c,56),view.getLayoutParams()==null?0:view.getLayoutParams().width);File file=coverFile(c,track);String key=file==null?id:file.getPath()+":"+file.length()+":"+file.lastModified()+":"+wanted;view.setTag(key);
            view.setImageTintList(ColorStateList.valueOf(color(c,R.color.on_surface_variant)));
            view.setImageResource(R.drawable.ic_note);view.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
            view.setBackgroundColor(color(c,R.color.surface_container));Bitmap found=cache.get(key);if(found!=null){show(view,found);return;}
            if(closed||file==null||!file.isFile())return;
            WeakReference<ArtworkView> weak=new WeakReference<>(view);
            pool.execute(()->{Bitmap loaded=decodeCover(file,wanted);if(loaded!=null)cache.put(key,loaded);main.post(()->{ArtworkView target=weak.get();if(!closed&&loaded!=null&&target!=null&&key.equals(target.getTag()))show(target,loaded);});});
        }
        private void show(ArtworkView v,Bitmap b){v.setImageTintList(null);v.setScaleType(ImageView.ScaleType.CENTER_CROP);v.setImageBitmap(b);}
        void close(){closed=true;pool.shutdownNow();cache.evictAll();}
    }
}
