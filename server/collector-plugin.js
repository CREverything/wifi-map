import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

const MAX_BODY_BYTES = 4096;
const MAX_OUTPUT_CHARS = 100000;
const EXTRACTOR_TIMEOUT_MS = 4 * 60 * 1000;
const RESULT_PREFIX = 'BRIDGE_RESULT:';
export const LOCAL_HOST = /^localhost(:\d+)?$|^127\.0\.0\.1(:\d+)?$/;

/** A collect request: browser-approved location plus the two collection toggles. */
export function isValidCollectRequest(request) {
  return Boolean(request) &&
    [request.latitude, request.longitude, request.accuracy_m].every(Number.isFinite) &&
    Math.abs(request.latitude) <= 90 && Math.abs(request.longitude) <= 180 && request.accuracy_m >= 0 &&
    typeof request.speedtest === 'boolean' && typeof request.firestore === 'boolean';
}

export function pythonExecutable(root) {
  const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (process.env.PYTHON_EXECUTABLE) return process.env.PYTHON_EXECUTABLE;
  if (existsSync(venvPython)) return venvPython;
  return process.platform === 'win32' ? 'python' : 'python3';
}

/** Dev-server endpoint POST /api/collect that runs extractor/bridge.py once. */
export default function collectorPlugin() {
  let activeChild = null;
  return {
    name: 'local-laptop-collector',
    configureServer(server) {
      server.httpServer?.on('close', () => activeChild?.kill());
      server.middlewares.use('/api/collect', (req, res) => {
        const reply = (status, body) => {
          res.statusCode = status;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(body));
        };
        if (req.method !== 'POST') return reply(405, { error: 'Use POST.' });
        const host = req.headers.host || '';
        if (!req.headers.origin || req.headers.origin !== `http://${host}` || !LOCAL_HOST.test(host)) {
          return reply(403, { error: 'Local same-origin requests only.' });
        }
        if (!req.headers['content-type']?.startsWith('application/json')) return reply(415, { error: 'JSON required.' });
        if (activeChild) return reply(409, { error: 'A measurement is already running.' });

        let body = '';
        let bodyTooLarge = false;
        req.on('data', (chunk) => {
          body += chunk;
          if (body.length > MAX_BODY_BYTES) {
            bodyTooLarge = true;
            body = '';
          }
        });
        req.on('end', () => {
          let collectRequest;
          try {
            collectRequest = JSON.parse(body);
          } catch {
            return reply(400, { error: 'Invalid JSON.' });
          }
          if (bodyTooLarge || !isValidCollectRequest(collectRequest)) {
            return reply(400, { error: 'Invalid location or collection settings.' });
          }
          if (activeChild) return reply(409, { error: 'A measurement is already running.' });

          const root = server.config.root;
          const child = spawn(pythonExecutable(root), [path.join(root, 'extractor/bridge.py')], {
            cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
          });
          activeChild = child;
          let output = '';
          let finished = false;
          const finish = (status, result) => {
            if (finished) return;
            finished = true;
            clearTimeout(timeout);
            activeChild = null;
            reply(status, result);
          };
          const timeout = setTimeout(() => {
            child.kill();
            finish(504, { error: 'Extractor exceeded four minutes and was stopped.' });
          }, EXTRACTOR_TIMEOUT_MS);

          child.stdout.on('data', (data) => { output = (output + data).slice(-MAX_OUTPUT_CHARS); });
          child.stderr.on('data', () => {});
          child.stdin.on('error', () => {});
          child.on('error', () => finish(503, {
            error: 'Python could not start. Install Python and the requirements, or set PYTHON_EXECUTABLE.',
          }));
          child.on('close', (code) => {
            if (code !== 0) {
              return finish(503, {
                error: 'Extractor failed. Check Python, requirements.txt, and local Firebase credentials if upload is enabled.',
              });
            }
            try {
              const resultLine = output.split(/\r?\n/).findLast((line) => line.startsWith(RESULT_PREFIX));
              finish(200, JSON.parse(resultLine.slice(RESULT_PREFIX.length)));
            } catch {
              finish(502, { error: 'Extractor returned no valid result.' });
            }
          });
          child.stdin.end(JSON.stringify(collectRequest));
        });
      });
    },
  };
}
