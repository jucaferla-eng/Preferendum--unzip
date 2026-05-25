const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// Treat .html files as assets so they can be bundled with the app
config.resolver.assetExts.push('html');

module.exports = config;
