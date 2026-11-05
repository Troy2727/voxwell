// Downloads the uv builds an installer for this OS bundles, into vendor/uv/<os>-<arch>/, and checks
// them against the checksums pinned here. To update uv, change the version and hashes together.
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const VERSION = '0.12.5';
const RELEASE = `https://github.com/astral-sh/uv/releases/download/${VERSION}`;
const LICENSE = `https://raw.githubusercontent.com/astral-sh/uv/${VERSION}/LICENSE-MIT`;
const BUILDS = {
  win32: [{ folder: 'win-x64', file: 'uv-x86_64-pc-windows-msvc.zip', sha256: '4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a' }],
  darwin: [
    { folder: 'mac-arm64', file: 'uv-aarch64-apple-darwin.tar.gz', sha256: '5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62' },
    { folder: 'mac-x64', file: 'uv-x86_64-apple-darwin.tar.gz', sha256: 'b3b2137477cf96c9686ebfb71524614cec780c673fd73e59bce099aef02e70e8' },
  ],
  linux: [{ folder: 'linux-x64', file: 'uv-x86_64-unknown-linux-gnu.tar.gz', sha256: '68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2' }],
};

async function download(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Downloading ${url} failed: HTTP ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

/** Unpacks an archive and moves its uv binary into `target`; only that file is kept. */
function unpack(archive, target) {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'voxwell-uv-'));
  try {
    // Windows may find Git's tar first, which can't read zip files or paths with a drive letter.
    if (process.platform === 'win32') {
      execFileSync('powershell.exe', ['-NoProfile', '-Command', 'Expand-Archive -LiteralPath $env:UV_ARCHIVE -DestinationPath $env:UV_TARGET'], {
        env: { ...process.env, UV_ARCHIVE: archive, UV_TARGET: work },
      });
    } else {
      execFileSync('tar', ['-xf', archive, '-C', work]);
    }
    const name = process.platform === 'win32' ? 'uv.exe' : 'uv';
    const found = fs.readdirSync(work, { recursive: true }).map(String).find((p) => path.basename(p) === name);
    if (!found) throw new Error(`${path.basename(archive)} has no ${name}`);
    fs.copyFileSync(path.join(work, found), path.join(target, name));
    fs.chmodSync(path.join(target, name), 0o755);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

(async () => {
  const license = await download(LICENSE);
  for (const build of BUILDS[process.platform]) {
    const target = path.join(__dirname, '..', 'vendor', 'uv', build.folder);
    fs.mkdirSync(target, { recursive: true });
    const data = await download(`${RELEASE}/${build.file}`);
    const actual = createHash('sha256').update(data).digest('hex');
    if (actual !== build.sha256) throw new Error(`${build.file} has the wrong checksum: ${actual}`);
    const archive = path.join(target, build.file);
    fs.writeFileSync(archive, data);
    unpack(archive, target);
    fs.rmSync(archive);
    fs.writeFileSync(path.join(target, 'LICENSE-MIT'), license);
    console.log(`uv ${VERSION} ready in ${target}`);
  }
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
