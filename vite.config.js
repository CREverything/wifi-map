import { defineConfig } from 'vite';
import collectorPlugin from './server/collector-plugin.js';
import predictionsPlugin from './server/predictions-plugin.js';

export default defineConfig({ plugins: [collectorPlugin(), predictionsPlugin()], server: { host: '127.0.0.1' } });
