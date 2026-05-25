import { useState, useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text } from 'react-native';
import { WebView } from 'react-native-webview';
import { Asset } from 'expo-asset';

const BG = '#0a0d14';

export default function App() {
  const [uri,   setUri]   = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        // fromModule is synchronous; downloadAsync ensures the file is on disk
        const asset = Asset.fromModule(require('./assets/app.html'));
        await asset.downloadAsync();

        if (!asset.localUri) {
          throw new Error('asset.localUri is null after downloadAsync');
        }

        setUri(asset.localUri);
      } catch (e) {
        setError(String(e));
      }
    })();
  }, []);

  if (error) {
    return (
      <View style={[styles.loading, { padding: 24 }]}>
        <Text style={{ color: '#f43f5e', fontSize: 13, textAlign: 'center' }}>
          {error}
        </Text>
      </View>
    );
  }

  if (!uri) {
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
        source={{ uri }}
        originWhitelist={['*']}
        javaScriptEnabled
        domStorageEnabled
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        // Required so file:// pages can fetch https:// API endpoints
        allowUniversalAccessFromFileURLs
        allowFileAccess
        mixedContentMode="always"
        onError={e => setError(e.nativeEvent.description || 'WebView error')}
        onHttpError={e => console.warn('HTTP error:', e.nativeEvent.statusCode)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: BG },
  webview:   { flex: 1, backgroundColor: BG },
  loading:   { flex: 1, backgroundColor: BG, alignItems: 'center', justifyContent: 'center' },
});
