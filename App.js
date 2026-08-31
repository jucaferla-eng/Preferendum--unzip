import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text, AppState, Linking, NativeModules, Platform } from 'react-native';
import { WebView } from 'react-native-webview';
import { useState, useRef, useEffect } from 'react';
import * as SecureStore from 'expo-secure-store';

const BG      = '#0a0d14';
const ACCENT  = '#2d6eff';
const APP_URL    = 'https://preferendum-unzip.onrender.com/voter';
const APP_ORIGIN = 'preferendum-unzip.onrender.com';

// COMPLETE INTERNATIONALIZATION REMEDIATION (Section 10) — the "brand" and
// "offline error" text is rendered by NATIVE React Native components
// OUTSIDE the WebView's DOM, so none of the web-based mechanisms
// (lang.js/Google Translate/UI_STRINGS) can reach it. This is the
// smallest safe native-side counterpart: a tiny 12-language string table
// (matching lang.js's SUPPORTED_LANGUAGES exactly) plus a lightweight
// device-locale + persisted-preference resolver. No new native
// permissions and no new npm dependency (NativeModules is core
// react-native; expo-secure-store is already an existing project
// dependency, listed in app.json's plugins).
const SUPPORTED_LANGUAGES = ['es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ar', 'ru', 'hi'];
const GLOBAL_FALLBACK_LANGUAGE = 'es';
const BRIDGED_LANG_KEY = 'pref_lang_bridged_from_webview';

const NATIVE_STRINGS = {
  es: { brand: 'Preferendum', offline: 'Sin conexión — verifica tu internet' },
  en: { brand: 'Preferendum', offline: 'No connection — check your internet' },
  pt: { brand: 'Preferendum', offline: 'Sem conexão — verifique sua internet' },
  fr: { brand: 'Preferendum', offline: 'Pas de connexion — vérifiez votre internet' },
  de: { brand: 'Preferendum', offline: 'Keine Verbindung — Internet prüfen' },
  it: { brand: 'Preferendum', offline: 'Nessuna connessione — verifica la tua rete' },
  ja: { brand: 'Preferendum', offline: '接続がありません — インターネットを確認してください' },
  ko: { brand: 'Preferendum', offline: '연결 없음 — 인터넷 연결을 확인하세요' },
  zh: { brand: 'Preferendum', offline: '无连接 — 请检查您的网络' },
  ar: { brand: 'Preferendum', offline: 'لا يوجد اتصال — تحقق من الإنترنت' },
  ru: { brand: 'Preferendum', offline: 'Нет соединения — проверьте интернет' },
  hi: { brand: 'Preferendum', offline: 'कोई कनेक्शन नहीं — अपना इंटरनेट जांचें' },
};

function normalizeLangTag(tag) {
  if (!tag) return '';
  // I18N FINAL HARDENING (Section 7) — verified on a real iOS Simulator
  // (`defaults read -g AppleLocale`) that AppleLocale returns underscore
  // form ("es_CL"), while AppleLanguages[0] returns hyphen/BCP-47 form
  // ("es-CL"). getDeviceLanguageTag() prefers AppleLocale, so splitting
  // on '-' alone silently failed to extract "es" from "es_CL" (returned
  // "es_cl" instead, which never matches SUPPORTED_LANGUAGES) — a real
  // bug this simulator check caught before it shipped. Split on either.
  const primary = String(tag).split(/[-_]/)[0].toLowerCase();
  return primary === 'zh' ? 'zh' : primary;
}

// Zero-new-dependency device locale read (iOS). Mirrors the same kind of
// signal navigator.language gives the web side, without expo-localization.
function getDeviceLanguageTag() {
  try {
    if (Platform.OS === 'ios') {
      const settings = NativeModules.SettingsManager && NativeModules.SettingsManager.settings;
      const raw = (settings && (settings.AppleLocale || (settings.AppleLanguages && settings.AppleLanguages[0]))) || '';
      return raw;
    }
    if (Platform.OS === 'android') {
      const raw = (NativeModules.I18nManager && NativeModules.I18nManager.localeIdentifier) || '';
      return raw;
    }
  } catch (e) { /* fall through to empty */ }
  return '';
}

// Same precedence shape as lang.js's resolveLanguage, scoped to what's
// available natively: a bridged explicit choice (persisted from a prior
// WebView session) beats device language, which beats the global
// fallback. There is no native "profile country" signal, so tier 3/4 are
// not applicable here -- the web resolver already covers those once the
// WebView itself has loaded.
function resolveNativeLanguage(bridgedLang, deviceTag) {
  const bridged = normalizeLangTag(bridgedLang);
  if (bridged && SUPPORTED_LANGUAGES.indexOf(bridged) !== -1) return bridged;
  const device = normalizeLangTag(deviceTag);
  if (device && SUPPORTED_LANGUAGES.indexOf(device) !== -1) return device;
  return GLOBAL_FALLBACK_LANGUAGE;
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const [nativeLang, setNativeLang] = useState(resolveNativeLanguage(null, getDeviceLanguageTag()));
  const webRef = useRef(null);

  useEffect(() => {
    // Pick up a language the user explicitly chose on a PRIOR WebView
    // session (bridged via onMessage below) -- coordinates with the
    // persisted web preference without requiring the WebView to be
    // loaded/online right now.
    SecureStore.getItemAsync(BRIDGED_LANG_KEY)
      .then(stored => {
        if (stored) setNativeLang(resolveNativeLanguage(stored, getDeviceLanguageTag()));
      })
      .catch(() => { /* SecureStore unavailable — device-locale resolution already applied */ });
  }, []);

  useEffect(() => {
    const sub = AppState.addEventListener('change', state => {
      if (state === 'active' && webRef.current) {
        // Only ping to keep the server awake — do NOT reload the page,
        // as that would reset the user's position in the voting flow.
        webRef.current.injectJavaScript(`
          fetch('${APP_URL}health').catch(()=>{});
          true;
        `);
      }
    });
    return () => sub.remove();
  }, []);

  const strings = NATIVE_STRINGS[nativeLang] || NATIVE_STRINGS[GLOBAL_FALLBACK_LANGUAGE];

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" backgroundColor={BG} />

      {(!ready || error) && (
        <View style={styles.overlay}>
          <Text style={styles.brand}>{strings.brand}</Text>
          {!error
            ? <ActivityIndicator size="large" color={ACCENT} style={{ marginTop: 24 }} />
            : <Text style={styles.errorText}>{strings.offline}</Text>
          }
        </View>
      )}

      <WebView
        ref={webRef}
        style={[styles.webview, !ready && styles.hidden]}
        source={{ uri: APP_URL }}
        originWhitelist={['*']}
        javaScriptEnabled={true}
        domStorageEnabled={true}
        allowsInlineMediaPlayback={true}
        mediaPlaybackRequiresUserAction={false}
        mediaCapturePermissionGrantType="grant"
        allowsProtectedMedia={true}
        onShouldStartLoadWithRequest={(req) => {
          // External links (ads, blockchain explorer, etc.) open in Safari
          if (!req.url.includes(APP_ORIGIN)) {
            Linking.openURL(req.url).catch(() => {});
            return false;
          }
          return true;
        }}
        onPermissionRequest={(e) => e.nativeEvent.request.grant(e.nativeEvent.request.resources)}
        onLoadEnd={() => { setReady(true); setError(false); }}
        onError={() => setError(true)}
        onHttpError={(e) => {
          if (e.nativeEvent.statusCode >= 500) setError(true);
        }}
        onMessage={(e) => {
          // lang.js (web side) posts {type:'preferendum:langchange', lang}
          // whenever the user explicitly picks a language — persisted here
          // so the native shell's own chrome (this overlay) can match it
          // on the NEXT cold start, before the WebView has loaded.
          try {
            const msg = JSON.parse(e.nativeEvent.data);
            if (msg && msg.type === 'preferendum:langchange' && msg.lang) {
              setNativeLang(resolveNativeLanguage(msg.lang, getDeviceLanguageTag()));
              SecureStore.setItemAsync(BRIDGED_LANG_KEY, msg.lang).catch(() => {});
            }
          } catch (err) { /* not our message shape — ignore */ }
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: BG },
  webview:   { flex: 1, backgroundColor: BG },
  hidden:    { opacity: 0 },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BG,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
  },
  brand: {
    color: '#ffffff',
    fontSize: 32,
    fontWeight: '700',
    letterSpacing: 2,
  },
  errorText: {
    color: '#ff4444',
    fontSize: 14,
    marginTop: 20,
    textAlign: 'center',
  },
});
