<script>
// The 20-second cut: the 60-second film is a pure function of time, so this plays chosen windows of it, sped up,
// with a flash and an impact on every jump, and a hook over the first seconds.
(function(){
const SEG = [ // [source start, source end, output length]
  [4.4, 7.4, 2.4], [7.4, 9.9, 2.0], [11.0, 17.0, 3.0], [21.4, 27.4, 3.0], [31.6, 37.9, 3.2], [41.0, 49.0, 3.6], [54.0, 59.6, 2.8]];
let o = 0; const S = SEG.map(([a, b, d]) => { const s = {a, b, d, o, sp: (b - a) / d}; o += d; return s; });
const F = window.renderAt;
const src = t => { const s = S.find(x => t < x.o + x.d) || S[S.length - 1]; return s.a + Math.min(t - s.o, s.d - 1e-3) * s.sp; };
const ui = document.getElementById('ui');
const hook = document.createElement('div');
hook.style.cssText = "position:absolute;left:0;right:0;top:140px;text-align:center;font:400 54px/0.98 Anton,Poppins;text-transform:uppercase;color:#F2F3F7;text-shadow:0 6px 30px rgba(0,0,0,.8)";
hook.innerHTML = 'What an AI agent does<br><span style="color:#FF6A3D">after you hit enter</span>';
ui.appendChild(hook);
const flash = document.createElement('div'); flash.style.cssText = 'position:absolute;inset:0;background:#FFF1E6;opacity:0;pointer-events:none'; document.body.appendChild(flash);
window.renderAt = t => {
  F(src(t));
  const h = t < 2.3 ? 1 : Math.max(0, 1 - (t - 2.3) / .3); hook.style.opacity = h; hook.style.transform = `scale(${1 + .03 * t})`;
  let f = 0; S.slice(1).forEach(s => { const d = t - s.o; if (d >= -.04 && d < .35) f = Math.max(f, Math.exp(-Math.max(d, 0) * 12)); });
  flash.style.opacity = (.55 * f).toFixed(3);
};
document.fonts.ready.then(() => {
  const out = [];
  (window.SOUNDS || []).forEach(([t, k]) => S.forEach(s => { if (t >= s.a && t < s.b) out.push([+(s.o + (t - s.a) / s.sp).toFixed(3), k]); }));
  S.slice(1).forEach(s => { out.push([s.o, 'impact']); out.push([s.o - .5, 'swirl']); });
  out.push([0, 'impact']); out.push([.05, 'sparkle']);
  window.SOUNDS = out.filter(x => x[0] >= 0 && x[0] < 20).sort((a, b) => a[0] - b[0]);
  window.renderAt(0);
});
})();
</script>
