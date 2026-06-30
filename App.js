import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text } from 'react-native';
import { WebView } from 'react-native-webview';
import { useState, useRef } from 'react';
import { Asset } from 'expo-asset';
import * as FileSystem from 'expo-file-system';
import { useEffect } from 'react';

const BG      = '#0a0d14';
const ACCENT  = '#2d6eff';
const BACKEND = 'https://preferendum-unzip.onrender.com';

export default function App() {
  const [html, setHtml]         = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [webReady, setWebReady] = useState(false);
  const webRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const [asset] = await Asset.loadAsync(require('./assets/app.html'));
        const content = await FileSystem.readAsStringAsync(asset.localUri);
        setHtml(content);
      } catch (e) {
        console.error('[App] Failed to load app.html from asset:', e);
        setLoadError(true);
      }
    })();
  }, []);

  // Error state — fall back to loading directly from Render
  if (loadError) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar style="light" backgroundColor={BG} />
        <WebView
          ref={webRef}
          style={styles.webview}
          source={{ uri: BACKEND }}
          originWhitelist={['*']}
          javaScriptEnabled={true}
          domStorageEnabled={true}
          allowsInlineMediaPlayback={true}
          mediaPlaybackRequiresUserAction={false}
          onError={(e) => console.warn('[WebView] error:', e.nativeEvent)}
        />
      </SafeAreaView>
    );
  }

  // Still loading asset from bundle
  if (!html) {
    return (
      <View style={styles.loading}>
        <StatusBar style="light" backgroundColor={BG} />
        <Text style={styles.brand}>Preferendum</Text>
        <ActivityIndicator size="large" color={ACCENT} style={{ marginTop: 24 }} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" backgroundColor={BG} />
      {!webReady && (
        <View style={styles.overlay}>
          <Text style={styles.brand}>Preferendum</Text>
          <ActivityIndicator size="large" color={ACCENT} style={{ marginTop: 24 }} />
        </View>
      )}
      <WebView
        ref={webRef}
        style={[styles.webview, !webReady && styles.hidden]}
        source={{ html, baseUrl: BACKEND }}
        originWhitelist={['*']}
        javaScriptEnabled={true}
        domStorageEnabled={true}
        allowsInlineMediaPlayback={true}
        mediaPlaybackRequiresUserAction={false}
        onLoadEnd={() => setWebReady(true)}
        onError={(e) => {
          console.warn('[WebView] error:', e.nativeEvent);
          setLoadError(true);
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: BG },
  webview:   { flex: 1, backgroundColor: BG },
  hidden:    { opacity: 0 },
  loading: {
    flex: 1,
    backgroundColor: BG,
    alignItems: 'center',
    justifyContent: 'center',
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BG,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
  },
  brand: {
    color: '#ffffff',
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 1,
  },
});
