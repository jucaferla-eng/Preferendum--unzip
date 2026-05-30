import { useState, useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text } from 'react-native';
import { WebView } from 'react-native-webview';
import { Asset } from 'expo-asset';
import * as FileSystem from 'expo-file-system/legacy';

const BG       = '#090D18';
const APP_URL  = 'https://preferendum-unzip-d2zd.onrender.com/app';

export default function App() {
  const [html,  setHtml]  = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => { loadHtml(); }, []);

  async function loadHtml() {
    try {
      // Intentar cargar desde el servidor (cambios instantáneos sin rebuild)
      const resp = await fetch(APP_URL, { timeout: 10000 });
      if (resp.ok) {
        const content = await resp.text();
        if (content && content.length > 500) {
          setHtml(content);
          return;
        }
      }
    } catch (e) {
      console.log('Server not available, falling back to local bundle');
    }

    // Fallback: bundle local (funciona sin internet)
    try {
      const asset = Asset.fromModule(require('./assets/app.html'));
      await asset.downloadAsync();
      if (!asset.localUri) throw new Error('asset.localUri is null');
      const content = await FileSystem.readAsStringAsync(asset.localUri);
      if (!content || content.length < 500) throw new Error(`HTML too short (${content?.length ?? 0} chars)`);
      setHtml(content);
    } catch (e) {
      setError(String(e));
    }
  }

  if (error) {
    return (
      <View style={[styles.loading, { padding: 32 }]}>
        <Text style={{ color: '#f43f5e', fontSize: 13, textAlign: 'center', lineHeight: 20 }}>
          {error}
        </Text>
        <Text onPress={loadHtml} style={{ color: '#2563eb', fontSize: 14, marginTop: 20, fontWeight: '700' }}>
          Retry
        </Text>
      </View>
    );
  }

  if (!html) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color="#2563eb" />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" backgroundColor={BG} />
      <WebView
        style={styles.webview}
        source={{ html, baseUrl: APP_URL }}
        originWhitelist={['*']}
        javaScriptEnabled
        domStorageEnabled
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        onError={e => setError('WebView: ' + (e.nativeEvent.description || e.nativeEvent.code))}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: BG },
  webview:   { flex: 1, backgroundColor: BG },
  loading:   { flex: 1, backgroundColor: BG, alignItems: 'center', justifyContent: 'center' },
});
