import { useState, useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import { SafeAreaView, StyleSheet, ActivityIndicator, View, Text } from "react-native";
import { WebView } from "react-native-webview";
import { Asset } from "expo-asset";
import * as FileSystem from "expo-file-system/legacy";
import * as SecureStore from "expo-secure-store";

const BG      = "#090D18";
const APP_URL = "https://preferendum-unzip-d2zd.onrender.com/app";

async function getOrCreateDeviceId() {
  try {
    let id = await SecureStore.getItemAsync("pref_device_id");
    if (!id) {
      id = "dev-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
      await SecureStore.setItemAsync("pref_device_id", id);
    }
    return id;
  } catch (_) {
    return "dev-" + Math.random().toString(36).slice(2, 18);
  }
}

export default function App() {
  const [html,     setHtml]     = useState(null);
  const [error,    setError]    = useState(null);
  const [deviceId, setDeviceId] = useState(null);

  useEffect(() => {
    getOrCreateDeviceId().then(setDeviceId);
    loadHtml();
  }, []);

  async function loadHtml() {
    // Load local bundle first — instant, no network needed
    try {
      const asset = Asset.fromModule(require("./assets/app.html"));
      await asset.downloadAsync();
      if (!asset.localUri) throw new Error("asset.localUri is null");
      const content = await FileSystem.readAsStringAsync(asset.localUri);
      if (!content || content.length < 500) throw new Error(`HTML too short (${content?.length ?? 0} chars)`);
      setHtml(content);
    } catch (e) {
      setError(String(e));
      return;
    }

    // Background check: quietly fetch server update (won t block launch)
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 4000);
      const resp = await fetch(`${APP_URL}?v=${Date.now()}`, { signal: ctrl.signal });
      clearTimeout(timer);
      if (resp.ok) {
        const content = await resp.text();
        if (content && content.length > 500) setHtml(content);
      }
    } catch (_) {
      // server unavailable — local bundle already shown, nothing to do
    }
  }

  if (error) {
    return (
      <View style={[styles.loading, { padding: 32 }]}>
        <Text style={{ color: "#f43f5e", fontSize: 13, textAlign: "center", lineHeight: 20 }}>{error}</Text>
        <Text onPress={loadHtml} style={{ color: "#2563eb", fontSize: 14, marginTop: 20, fontWeight: "700" }}>Retry</Text>
      </View>
    );
  }

  if (!html || !deviceId) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color="#2563eb" />
      </View>
    );
  }

  const injected = `window.DEVICE_ID=${JSON.stringify(deviceId)};window.DEVICE_MODEL="mobile";true;`;

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="light" backgroundColor={BG} />
      <WebView
        style={styles.webview}
        source={{ html, baseUrl: APP_URL }}
        originWhitelist={["*"]}
        javaScriptEnabled
        domStorageEnabled
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        injectedJavaScriptBeforeContentLoaded={injected}
        allowsLinkPreview={false}
        onError={e => setError("WebView: " + (e.nativeEvent.description || e.nativeEvent.code))}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: BG },
  webview:   { flex: 1, backgroundColor: BG },
  loading:   { flex: 1, backgroundColor: BG, alignItems: "center", justifyContent: "center" },
});
