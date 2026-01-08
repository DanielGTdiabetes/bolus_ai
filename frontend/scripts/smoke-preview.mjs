import { spawn } from 'node:child_process';

const port = process.env.SMOKE_PORT || '4173';
const host = process.env.SMOKE_HOST || '0.0.0.0';
const preview = spawn('npm', ['run', 'preview', '--', '--host', host, '--port', port], {
  stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, BROWSER: 'none' }
});

let ready = false;
let output = '';

const waitForReady = () =>
  new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      if (!ready) {
        reject(new Error('Preview server did not start in time.'));
      }
    }, 15000);

    preview.stdout.on('data', (data) => {
      const text = data.toString();
      output += text;
      if (text.includes('Local:') || text.includes('http://')) {
        ready = true;
        clearTimeout(timeout);
        resolve();
      }
    });

    preview.stderr.on('data', (data) => {
      output += data.toString();
    });
  });

const shutdown = () => {
  if (!preview.killed) {
    preview.kill('SIGTERM');
  }
};

process.on('exit', shutdown);
process.on('SIGINT', () => {
  shutdown();
  process.exit(1);
});

try {
  await waitForReady();
  const response = await fetch(`http://localhost:${port}/`);
  if (!response.ok) {
    throw new Error(`Unexpected status: ${response.status}`);
  }
  const html = await response.text();
  if (!html.includes('id="app"')) {
    throw new Error('Missing #app container in HTML response.');
  }
  console.log('Smoke preview OK.');
  shutdown();
  process.exit(0);
} catch (error) {
  shutdown();
  console.error('Smoke preview failed:', error.message);
  if (output) {
    console.error('Preview output:\n', output.trim());
  }
  process.exit(1);
}
