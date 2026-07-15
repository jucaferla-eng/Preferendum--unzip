import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text, AppState, Linking } from 'react-native';
import { WebView } from 'react-native-webview';
import { useState, useRef, useEffect } from 'react';

const BG      = '#0a0d14';
const ACCENT  = '#2d6eff';
const APP_URL    = 'https://preferendum-unzip.onrender.com/';
const APP_ORIGIN = 'preferendum-unzip.onrender.com';

export default function App() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const webRef = useRef(null);

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

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" backgroundColor={BG} />

      {(!ready || error) && (
        <View style={styles.overlay}>
          <Text style={styles.brand}>Preferendum</Text>
          {!error
            ? <ActivityIndicator size="large" color={ACCENT} style={{ marginTop: 24 }} />
            : <Text style={styles.errorText}>Sin conexión — verifica tu internet</Text>
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
