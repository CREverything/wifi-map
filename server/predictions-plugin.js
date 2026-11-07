import { spawn } from 'node:child_process';
import { LOCAL_HOST, pythonExecutable } from './collector-plugin.js';

const FEED_TIMEOUT_MS = 60 * 1000;
const MAX_OUTPUT_CHARS = 20 * 1024 * 1024;
const RESULT_PREFIX = 'MAP_FEED_RESULT:';

/**
 * Dev-server endpoint GET /api/predictions. Runs `python -m model.map_feed`, which
 * reads Firestore `predictions` with the laptop's Admin credentials, so no keys or
 * Firebase config reach the browser and the security rules can stay closed.
 */
export default function predictionsPlugin() {
  let activeChild = null;
  return {
    name: 'firestore-predictions-feed',
    configureServer(server) {
      server.httpServer?.on('close', () => activeChild?.kill());
      server.middlewares.use('/api/predictions', (req, res) => {
        const reply = (status, body) => {
          res.statusCode = status;
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Cache-Control', 'no-store');
          res.end(JSON.stringify(body));
        };
        if (req.method !== 'GET') return reply(405, { error: 'Use GET.' });
        const host = req.headers.host || '';
        // Same-origin GETs usually omit Origin; when present it must match.
        if (!LOCAL_HOST.test(host) || (req.headers.origin && req.headers.origin !== `http://${host}`)) {
          return reply(403, { error: 'Local same-origin requests only.' });
        }
        if (activeChild) return reply(409, { error: 'Predictions are already loading.' });

        const root = server.config.root;
        const child = spawn(pythonExecutable(root), ['-m', 'model.map_feed'], {
          cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
        });
        activeChild = child;
        let output = '';
        let finished = false;
        const finish = (status, body) => {
          if (finished) return;
          finished = true;
          clearTimeout(timeout);
          activeChild = null;
          reply(status, body);
        };
        const timeout = setTimeout(() => {
          child.kill();
          finish(504, { error: 'Reading Firestore took longer than a minute.' });
        }, FEED_TIMEOUT_MS);

        child.stdout.on('data', (data) => { output = (output + data).slice(-MAX_OUTPUT_CHARS); });
        child.stderr.on('data', () => {}); // may contain credential paths; never forwarded
        child.on('error', () => finish(503, {
          error: 'Python could not start. Install Python and the requirements, or set PYTHON_EXECUTABLE.',
        }));
        child.on('close', (code) => {
          if (code !== 0) {
            return finish(503, { error: 'Could not read Firestore predictions. Check the root .env and service-account key.' });
          }
          try {
            const resultLine = output.split(/\r?\n/).findLast((line) => line.startsWith(RESULT_PREFIX));
            finish(200, JSON.parse(resultLine.slice(RESULT_PREFIX.length)));
          } catch {
            finish(502, { error: 'The predictions reader returned no valid result.' });
          }
        });
      });
    },
  };
}
