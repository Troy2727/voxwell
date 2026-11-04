// Answers health and transcription, and 404s the rest, like a backend with nothing in it.
const http = require('node:http');

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', req.headers.origin || '*');
  res.setHeader('Access-Control-Allow-Headers', '*');
  res.setHeader('Access-Control-Allow-Methods', '*');
  res.setHeader('Content-Type', 'application/json');
  if (req.method === 'OPTIONS') return res.writeHead(204).end();
  req.resume();
  req.on('end', () => {
    if (req.url === '/api/health') return res.end('{"status":"ok"}');
    if (req.url === '/api/dictation/transcribe') return res.end('{"text":"Overlay smoke test transcript.","language":"en"}');
    res.writeHead(404).end('{"detail":"Not found"}');
  });
});
server.listen(Number(process.env.VOXWELL_PORT), '127.0.0.1');
process.stdin.on('end', () => process.exit(0));
process.stdin.resume();
