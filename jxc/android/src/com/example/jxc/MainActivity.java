package com.example.jxc;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private static final String DEFAULT_URL = "http://192.168.1.2:8090/"; // 换成你服务器的地址，或在 App 里点右上角齿轮改
    private WebView web;
    private SharedPreferences sp;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        sp = getSharedPreferences("jxc", MODE_PRIVATE);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        web.setWebViewClient(new WebViewClient());

        FrameLayout root = new FrameLayout(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        float den = getResources().getDisplayMetrics().density;
        int gsz = (int) (48 * den);
        TextView gear = new TextView(this);
        gear.setText("⚙");
        gear.setTextSize(15);
        gear.setTextColor(Color.argb(110, 255, 255, 255));
        gear.setGravity(Gravity.CENTER);
        FrameLayout.LayoutParams gp = new FrameLayout.LayoutParams(gsz, gsz);
        gp.gravity = Gravity.TOP | Gravity.RIGHT;
        gp.topMargin = (int) (6 * den);
        root.addView(gear, gp);
        gear.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                askUrl(sp.getString("server_url", DEFAULT_URL));
            }
        });

        setContentView(root);

        String url = sp.getString("server_url", "");
        if (url.isEmpty()) {
            sp.edit().putString("server_url", DEFAULT_URL).apply();
            url = DEFAULT_URL;
        }
        web.loadUrl(url);
    }

    private void askUrl(String preset) {
        final EditText et = new EditText(this);
        et.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        et.setText(preset);
        new AlertDialog.Builder(this)
                .setTitle("服务器地址")
                .setView(et)
                .setPositiveButton("保存", (d, w) -> {
                    String u = et.getText().toString().trim();
                    if (!u.startsWith("http")) u = "http://" + u;
                    if (!u.endsWith("/")) u = u + "/";
                    sp.edit().putString("server_url", u).apply();
                    web.loadUrl(u);
                })
                .setNegativeButton("取消", (d, w) -> {
                })
                .show();
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
