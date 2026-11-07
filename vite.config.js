import { defineConfig } from 'vite';
import collectorPlugin from './server/collector-plugin.js';
export default defineConfig({plugins:[collectorPlugin()],server:{host:'127.0.0.1'}});
