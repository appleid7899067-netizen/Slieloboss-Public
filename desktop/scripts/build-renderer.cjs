const fs = require('node:fs');
const path = require('node:path');

const desktopDir = path.resolve(__dirname, '..');
const outDir = path.join(desktopDir, 'dist', 'renderer');

if (process.env.VERCEL) {
  const webDir = path.resolve(desktopDir, '..', 'channel', 'web');
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  fs.cpSync(webDir, outDir, { recursive: true });
  console.log(`Vercel web build copied from ${webDir} to ${outDir}`);
} else {
  const { execFileSync } = require('node:child_process');
  execFileSync(process.platform === 'win32' ? 'npx.cmd' : 'npx', ['vite', 'build'], {
    cwd: desktopDir,
    stdio: 'inherit',
  });
}
