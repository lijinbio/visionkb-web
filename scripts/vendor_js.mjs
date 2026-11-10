// Copy the pinned marked and DOMPurify builds (package-lock.json) into the static folder, with their licenses.
// `node scripts/vendor_js.mjs --check` fails when the vendored files differ from node_modules (CI).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const nm = join(root, 'node_modules');
const out = join(root, 'src', 'visionkb_web', 'static');
const version = (pkg) => JSON.parse(readFileSync(join(nm, pkg, 'package.json'), 'utf8')).version;
const files = [
  ['marked/lib/marked.esm.js', 'js/vendor/marked.esm.js'],
  ['dompurify/dist/purify.es.mjs', 'js/vendor/purify.es.js'],
  ['marked/LICENSE', 'vendor-licenses/marked-LICENSE.txt'],
  ['dompurify/LICENSE', 'vendor-licenses/dompurify-LICENSE.txt'],
  ['dompurify/LICENSE-MPL', 'vendor-licenses/dompurify-LICENSE-MPL.txt'],
];
const check = process.argv.includes('--check');
let bad = 0;
for (const [src, dst] of files) {
  const data = readFileSync(join(nm, src));
  const target = join(out, dst);
  if (check) {
    let cur = null;
    try { cur = readFileSync(target); } catch { /* missing */ }
    if (!cur || !cur.equals(data)) { console.error(`differs: ${dst} (run npm run vendor)`); bad += 1; }
  } else {
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, data);
  }
}
const versions = { marked: version('marked'), dompurify: version('dompurify') };
const manifest = JSON.stringify(versions, null, 2) + '\n';
const mpath = join(out, 'js', 'vendor', 'VERSIONS.json');
if (check) {
  let cur = '';
  try { cur = readFileSync(mpath, 'utf8'); } catch { /* missing */ }
  if (cur !== manifest) { console.error('differs: js/vendor/VERSIONS.json'); bad += 1; }
  if (bad) process.exit(1);
  console.log('vendored files match', versions);
} else {
  writeFileSync(mpath, manifest);
  console.log('vendored', versions);
}
