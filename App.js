import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, ActivityIndicator, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { useState } from 'react';
import { Asset } from 'expo-asset';
import * as FileSystem from 'expo-file-system';
import { useEffect } from 'react';

const BG = '#0a0d14';

export default function App() {
  const [html, setHtml] = useState(null);

  useEffect(() => {
    (async () => {
      const [asset] = await Asset.loadAsync(require('./assets/app.html'));
      const content = await FileSystem.readAsStringAsync(asset.localUri);
      setHtml(content);
    })();
  }, []);

  if (!html) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color="#2d6eff" />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" backgroundColor={BG} />
      <WebView
        style={styles.webview}
        source={{ html, baseUrl: 'https://preferendum-unzip.onrender.com' }}
        originWhitelist={['*']}
        javaScriptEnabled={true}
        domStorageEnabled={true}
        allowsInlineMediaPlayback={true}
        mediaPlaybackRequiresUserAction={false}
        onError={(e) => console.warn('WebView error:', e.nativeEvent)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: BG },
  webview:   { flex: 1, backgroundColor: BG },
  loading:   { flex: 1, backgroundColor: BG, alignItems: 'center', justifyContent: 'center' },
});
