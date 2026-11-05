// First launch of an installed app: a private copy of uv installs Python and the AI packages into
// the user's own folders. Nothing here runs from a source checkout, which uses the developer's uv.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const READY_FILE = '.voxwell-ready';
const MIN_FREE_BYTES = 12 * 1024 ** 3; // the install takes about 11 GB on Windows
const LOG_LINES = 12; // what a failure shows

class SetupError extends Error {}

function enginePaths({ resourcesPath, userData, version, platform = process.platform }) {
  const home = path.join(userData, 'engine');
  return {
    uv: path.join(resourcesPath, 'uv', platform === 'win32' ? 'uv.exe' : 'uv'),
    source: path.join(resourcesPath, 'backend'),
    home,
    // A writable copy per version: the install folder can be read-only, and an update replaces it.
    project: path.join(home, `backend-${version}`),
    env: {
      UV_SYSTEM_CERTS: '1', // or installing fails behind TLS-inspecting proxies and antivirus
      UV_PROJECT_ENVIRONMENT: path.join(home, 'env'),
      UV_PYTHON_INSTALL_DIR: path.join(home, 'python'),
    },
  };
}

const isReady = (paths) => fs.existsSync(path.join(paths.project, READY_FILE));

async function checkFreeSpace(paths, minFree) {
  if (fs.existsSync(paths.env.UV_PROJECT_ENVIRONMENT)) return; // an update reuses most of what's there
  const { bavail, bsize } = await fs.promises.statfs(paths.home);
  const free = bavail * bsize;
  if (free < minFree) {
    const gb = (bytes) => Math.round(bytes / 1024 ** 3);
    throw new SetupError(`Voxwell needs about ${gb(minFree)} GB of free disk space to set up, and this computer has ${gb(free)} GB. Free up some space and try again.`);
  }
}

/** Removes the copies left by earlier versions, once this one works. */
function removeOldProjects(paths) {
  for (const entry of fs.readdirSync(paths.home)) {
    const full = path.join(paths.home, entry);
    if (entry.startsWith('backend-') && full !== paths.project) fs.rmSync(full, { recursive: true, force: true });
  }
}

/** Runs the install; safe to run again, as uv keeps what it already downloaded. Rejects with SetupError. */
async function install(paths, { onLine = () => {}, onChild = () => {}, start = spawn, minFree = MIN_FREE_BYTES } = {}) {
  fs.mkdirSync(paths.home, { recursive: true });
  await checkFreeSpace(paths, minFree);
  fs.rmSync(paths.project, { recursive: true, force: true });
  fs.cpSync(paths.source, paths.project, { recursive: true });

  const recent = [];
  await new Promise((resolve, reject) => {
    const child = start(paths.uv, ['sync', '--frozen', '--no-dev'], {
      cwd: paths.project,
      env: { ...process.env, ...paths.env },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    onChild(child);
    const read = (chunk) => {
      for (const line of String(chunk).split(/\r?\n/)) {
        if (!line.trim()) continue;
        recent.push(line.trim());
        if (recent.length > LOG_LINES) recent.shift();
        onLine(line.trim());
      }
    };
    child.stdout.on('data', read);
    child.stderr.on('data', read);
    child.on('error', (e) => reject(new SetupError(`The installer could not start: ${e.message}`)));
    child.on('close', (code) => (code === 0 ? resolve() : reject(new SetupError(`Setup stopped before it finished. Check your internet connection and try again.\n\n${recent.join('\n')}`))));
  });
  fs.writeFileSync(path.join(paths.project, READY_FILE), '');
  removeOldProjects(paths);
}

module.exports = { enginePaths, install, isReady, SetupError, MIN_FREE_BYTES };
