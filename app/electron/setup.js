const working = document.getElementById('working');
const failed = document.getElementById('failed');

window.voxwellSetup.onProgress((line) => {
  document.getElementById('step').textContent = line;
});

window.voxwellSetup.onFailed((reason) => {
  document.getElementById('reason').textContent = reason;
  working.hidden = true;
  failed.hidden = false;
});

document.getElementById('retry').addEventListener('click', () => {
  failed.hidden = true;
  working.hidden = false;
  window.voxwellSetup.retry();
});

document.getElementById('quit').addEventListener('click', () => window.voxwellSetup.quit());
