import { useState, useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text } from 'react-native';
import { WebView } from 'react-native-webview';
import { Asset } from 'expo-asset';
import * as FileSystem from 'expo-file-system/legacy';

const BG      = '#090D18';
const API_URL = 'https://preferendum-unzip.onrender.com';

export default function App() {
  const [html,  setHtml]  = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => { loadHtml(); }, []);

  async function loadHtml() {
    try {
      // fromModule is synchronous; downloadAsync copies the bundled asset to disk
      const asset = Asset.fromModule(require('./assets/app.html'));
      await asset.downloadAsync();

      if (!asset.localUri) {
        throw new Error('asset.localUri is null — asset not cached on device');
      }

      const content = await FileSystem.readAsStringAsync(asset.localUri);

      if (!content || content.length < 500) {
        throw new Error(`HTML too short (${content?.length ?? 0} chars) — bundle may be corrupt`);
      }

      setHtml(content);
    } catch (e) {
      // Surface the error visibly so we can diagnose in TestFlight
      setError(String(e));
    }
  }

  // Visible error — never a silent infinite spinner
  if (error) {
    return (
      <View style={[styles.loading, { padding: 32 }]}>
        <Text style={{ color: '#f43f5e', fontSize: 13, textAlign: 'center', lineHeight: 20 }}>
          {error}
        </Text>
        <Text
          onPress={loadHtml}
          style={{ color: '#2563eb', fontSize: 14, marginTop: 20, fontWeight: '700' }}
        >
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
        // inline html + baseUrl makes fetch() calls go to the right origin
        // avoiding CORS issues. This is the reliable approach for local HTML on iOS.
        source={{ html, baseUrl: API_URL }}
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
