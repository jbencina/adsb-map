// Runtime configuration for a statically hosted build of the map UI.
//
// After `bun run build`, copy this file to `dist/config.js` and edit it. index.html
// loads /config.js before the app bundle, so no rebuild is needed to change these.
//
// When the UI is served by `adsb start backend` or `adsb start frontend`, this file is
// NOT used: those servers generate /config.js from MAPBOX_TOKEN at request time.
window.APP_CONFIG = {
  // Base URL of the `adsb start backend` host. Leave empty for same-origin.
  // The backend must allow this page's origin: `adsb start backend --cors-origins https://maps.example.com`
  apiUrl: 'http://receiver.local:8000',

  // Mapbox public token: https://account.mapbox.com/access-tokens/
  mapboxToken: 'pk.your_token_here',
}
