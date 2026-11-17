// Paste in place: press the OS paste keys in the focused app, after dictation put the text on the
// clipboard. Spawns the OS's own tool, so there is no native module. The text is never on a command line.
const { execFile } = require('node:child_process');

const TIMEOUT_MS = 5_000;

/** The command that presses paste on this system, or null when there is none to try. */
function pasteCommand(platform = process.platform, env = process.env) {
  if (platform === 'win32') {
    return { file: 'powershell.exe', args: ['-NoProfile', '-NonInteractive', '-Command', "(New-Object -ComObject WScript.Shell).SendKeys('^v')"] };
  }
  if (platform === 'darwin') {
    return { file: 'osascript', args: ['-e', 'tell application "System Events" to keystroke "v" using command down'] };
  }
  if (env.WAYLAND_DISPLAY) return { file: 'wtype', args: ['-M', 'ctrl', 'v', '-m', 'ctrl'] };
  if (env.DISPLAY) return { file: 'xdotool', args: ['key', '--clearmodifiers', 'ctrl+v'] };
  return null;
}

/** Why pasting failed, in a few words for the overlay. The text is still on the clipboard. */
function reasonFor(err, command, platform) {
  if (err.code === 'ENOENT') return `Install ${command.file} to paste in place.`;
  // osascript itself is always there; what fails is the Accessibility permission.
  if (platform === 'darwin') return 'Allow Voxwell in Accessibility settings to paste.';
  return "Couldn't paste in place.";
}

/** Resolves to { pasted: true }, or { pasted: false, reason }. Never rejects. */
function paste({ platform = process.platform, env = process.env, run = execFile } = {}) {
  const command = pasteCommand(platform, env);
  if (!command) return Promise.resolve({ pasted: false, reason: "Can't paste in place on this desktop." });
  return new Promise((resolve) => {
    run(command.file, command.args, { timeout: TIMEOUT_MS, windowsHide: true }, (err) => {
      if (!err) resolve({ pasted: true });
      else {
        console.error('[dictation] paste failed:', err.message);
        resolve({ pasted: false, reason: reasonFor(err, command, platform) });
      }
    });
  });
}

module.exports = { paste, pasteCommand };
