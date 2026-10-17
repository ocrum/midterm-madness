// Runs the page's own script once in Node and writes a copy with every result
// filled in and no JavaScript, for viewers that don't run scripts (iPhone preview).
//   node pipeline/render_static.js site/app.html site/index.html
const fs = require('fs');
const vm = require('vm');
const [src, dst] = process.argv.slice(2);
const html = fs.readFileSync(src, 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

const els = {};
const el = id => els[id] || (els[id] = {
  id, innerHTML: null, textContent: null, value: '', checked: false, hidden: false, dataset: {},
  setAttribute() {}, addEventListener() {}, closest() { return null; },
});
const ctx = {
  STATIC: true, console, Math, JSON, Date, Array, Object, Set, String, Number, Uint8Array, Uint16Array, Int16Array,
  Float32Array, Float64Array, isFinite, parseFloat,
  document: { getElementById: el, addEventListener() {} },
  localStorage: { getItem() { return null; }, setItem() {} },
  setTimeout: fn => fn(),
};
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(script, ctx);

let out = html.replace(/<script>[\s\S]*<\/script>/, '');
for (const [id, e] of Object.entries(els)) {
  const content = e.innerHTML ?? e.textContent;
  if (content == null) continue;
  const re = new RegExp(`(<(\\w+)\\b[^>]*\\bid="${id}"[^>]*>)[\\s\\S]*?(</\\2>)`);
  out = out.replace(re, (m, open, tag, close) => open.replace(/\shidden(?=[\s>])/, '') + content + close);
}
out = out
  // no tabs without JavaScript: show every section, with jump links
  .replace(/<div class="tabs"[\s\S]*?<\/div>/, '<nav class="tabs"><a href="#pane-opt">Sheet</a><a href="#pane-work">Show work</a><a href="#pane-mine">My sheet</a><a href="#pane-src">Sources</a></nav>')
  .replace(/(<div id="pane-\w+" class="pane") hidden>/g, '$1>')
  .replace(/<div class="pad seg card">[\s\S]*?<\/div>/, '')
  .replace(/<div class="set">[\s\S]*?<\/div>\s*<div class="pad"><button[^>]*id="reset"[\s\S]*?<\/div>/, '')
  .replace(/<div class="pad"><button[^>]*id="mine-reset"[\s\S]*?<\/div>/, '')
  .replace(/<div class="pad seg"><button[^>]*id="g-sheet"[\s\S]*?<\/div>/, '')
  .replace('</style>', '.tabs a{flex:1;text-align:center;padding:10px 4px;font-weight:700;font-size:14px;text-decoration:none}\n</style>')
  .replace('<details>', '<details open>');
fs.writeFileSync(dst, out);
console.log('wrote', dst, Math.round(out.length / 1024), 'KB, no scripts:', !/<script/i.test(out));
