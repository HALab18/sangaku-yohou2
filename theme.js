/* PeakWeather — 配色の切り替え(自動 / ライト / ダーク)。全ページ共通。
 *
 * 既定は **自動**＝端末(OS)の設定に従う。ver 2.47β まではそれだけで、画面内に切り替えは
 * 無かった。2.48β で手動固定を足したのは「端末は暗いが、この画面だけは明るく見たい」
 * (逆も)という要望に、利用者が端末の設定を触らずに応えられるようにするため。
 *
 * ★ 保存するのは **手動で固定したときだけ**。「自動」に戻すとキーごと消す。
 *   「保存が無い＝自動」にしておくと、将来この既定を変えたときに古い端末だけが
 *   取り残されることがない(「auto」という値を書いてしまうとそれができない)。
 *
 * ★ ここで data-theme を "light" / "dark" の **どちらかに解決して** <html> に付ける。
 *   theme.css は解決後の1状態(:root[data-theme="dark"])だけを見ればよくなる。
 *   theme.css に @media(prefers-color-scheme:dark) を足さないこと ── 属性とメディアクエリの
 *   二重管理になり、片方だけ直したときに「端末が夜モードのときだけ古い色」になる。
 *
 * ★ <head> の中で、theme.css の直後に **同期読み込み**で置くこと(defer/async にしない)。
 *   遅らせると明るい配色で一度描いてから暗転する ── 2.47β で消した「起動時の白い一瞬」が戻る。
 *
 * ★ 版は theme.css の --pw-theme-ver と同じ値にし、各ページの `theme.js?v=` も揃える
 *   (配色の層としてひとつの版で動かす)。一致は scripts/check_contrast.py が機械的に見ている。
 */
var PW_THEME_VER = "248";

(function () {
  var KEY = "pw-theme";                 // 値は "light" / "dark" のみ。自動のときは未保存
  var MODES = ["auto", "light", "dark"];
  var LABEL = { auto: "自動", light: "ライト", dark: "ダーク" };
  /* ブラウザUI(アドレスバー)の色。ページ最上部はどちらの配色でも濃紺の面なので、
     各ページの <meta name="theme-color" media="…"> と同じ値を持つ。 */
  var BAR = { light: "#1e2d4a", dark: "#101725" };

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return (v === "light" || v === "dark") ? v : "auto";
    } catch (e) { return "auto"; }       // プライベートモード等で参照できないときは自動
  }

  function systemDark() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  /* アドレスバーの色。HTML 側の2枚は media 付きで **端末の設定**に従うので、手動固定のときは
     media 無しの1枚を先頭に差し込んで上書きする(同じ name が複数あるときブラウザは
     条件に合う **最初の1枚** を使う)。自動に戻したらその1枚を外し、HTML 側に任せる。 */
  function bar(mode, eff) {
    var head = document.head, own = document.getElementById("pw-bar");
    if (mode === "auto") { if (own) own.parentNode.removeChild(own); return; }
    if (!own) {
      own = document.createElement("meta");
      own.name = "theme-color";
      own.id = "pw-bar";
      var first = head.querySelector('meta[name="theme-color"]');
      head.insertBefore(own, first || head.firstChild);
    }
    own.setAttribute("content", BAR[eff]);
  }

  function apply(mode) {
    var eff = mode === "auto" ? (systemDark() ? "dark" : "light") : mode;
    document.documentElement.setAttribute("data-theme", eff);
    bar(mode, eff);
    return eff;
  }

  // ---- 起動時。描画前に当てる ----
  apply(read());

  /* OS 側の切り替えに追従する。「自動」のときだけ効かせる(手動で固定している人の画面が、
     日の入りと同時に勝手に反転しないように)。 */
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onSys = function () { if (read() === "auto") { apply("auto"); sync(); } };
    if (mq.addEventListener) mq.addEventListener("change", onSys);
    else if (mq.addListener) mq.addListener(onSys);          // 旧 Safari
  }

  /* 別のタブ/ページで切り替えたとき、開いたままのタブも追いつかせる。
     このアプリは予報(index)と山さがし(find)を行き来しながら使うので、
     片方だけ前の配色のままだと「切り替えが効いていない」ように見える。 */
  window.addEventListener("storage", function (e) {
    if (e.key === KEY || e.key === null) { apply(read()); sync(); }
  });

  // ---- 切り替え UI ----
  // フッタに <div class="pw-theme" id="themeui"></div> を置いたページに自動で組み立てる。
  function sync() {
    var box = document.getElementById("themeui");
    if (!box) return;
    var cur = read();
    var bs = box.querySelectorAll("button[data-m]");
    for (var i = 0; i < bs.length; i++)
      bs[i].setAttribute("aria-pressed", bs[i].getAttribute("data-m") === cur ? "true" : "false");
  }

  function mount() {
    var box = document.getElementById("themeui");
    if (!box || box.firstChild) return;
    var seg = document.createElement("div");
    seg.className = "pw-seg";
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "配色");
    MODES.forEach(function (m) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("data-m", m);
      b.textContent = LABEL[m];
      // 「自動」だけは何に追従するのかが名前から読み取れないので補う
      b.title = m === "auto" ? "端末の設定に合わせる" : LABEL[m] + "に固定する";
      b.addEventListener("click", function () { pwThemeSet(m); });
      seg.appendChild(b);
    });
    box.appendChild(seg);
    sync();
  }

  window.pwThemeSet = function (mode) {
    if (MODES.indexOf(mode) < 0) mode = "auto";
    try {
      if (mode === "auto") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch (e) { /* 保存できなくても、この画面の見た目だけは切り替える */ }
    apply(mode);
    sync();
  };
  window.pwThemeGet = function () { return read(); };
  window.pwThemeMount = mount;

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
