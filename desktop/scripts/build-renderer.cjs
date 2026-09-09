const fs = require('node:fs');
const path = require('node:path');

const desktopDir = path.resolve(__dirname, '..');
const outDir = path.join(desktopDir, 'dist', 'renderer');

if (process.env.VERCEL) {
  const webDir = path.resolve(desktopDir, '..', 'channel', 'web');
  const staticDir = path.join(webDir, 'static');

  // Vercel serves the renderer directory as the site root. The original
  // CowAgent web console is normally served by the Python backend, where
  // /assets maps to channel/web/static. Recreate that mapping for static
  // hosting and expose chat.html as the site root.
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  fs.copyFileSync(path.join(webDir, 'chat.html'), path.join(outDir, 'index.html'));
  fs.cpSync(staticDir, path.join(outDir, 'assets'), { recursive: true });

  // The standalone Vercel deployment has no Python backend. Expose a static
  // JSON-compatible /config resource so the existing console can initialize
  // without trying to parse a Vercel 404 page as JSON.
  const configFile = path.join(desktopDir, 'config');
  if (fs.existsSync(configFile)) {
    fs.copyFileSync(configFile, path.join(outDir, 'config'));
    console.log(`  config     <- ${configFile}`);
  }

  console.log(`Vercel web console prepared at ${outDir}`);
  console.log(`  index.html <- ${path.join(webDir, 'chat.html')}`);
  console.log(`  assets/    <- ${staticDir}`);
} else {
  const { execFileSync } = require('node:child_process');
  execFileSync(process.platform === 'win32' ? 'npx.cmd' : 'npx', ['vite', 'build'], {
    cwd: desktopDir,
    stdio: 'inherit',
  });
}
