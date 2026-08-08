"use strict";
/* PeakWeather 共通ゲート
 *
 * 利用規約への同意と認証コードの判定を、この1ファイルに集約する。
 * index.html / docs/find.html / docs/point.html の「操作ページ」すべてが読み込む。
 *
 * 認証コードの年次ローテーション (skill/auth-renew) で差し替えるのは
 * このファイルの AUTH_VER / AUTH_SALT / AUTH_HASH の3定数だけ。他のファイルには置かないこと。
 * 定数を複数箇所に複製すると、更新漏れで「認証済みなのに弾かれる」事故が起きる。
 *
 * KEY名は sangaku-yohou(v1) と別名にすること: 同じ halab18.github.io オリジンで
 * localStorage を共有するため、キー名が同じだと v1 で同意/認証済みの利用者が
 * v2 でも未入力のまま通ってしまう。
 */

var PW_AGREE_KEY = "sangaku-yohou2-agreed-v1";

/* 認証コード: コード本体は埋め込まず、ソルト付き PBKDF2-SHA256 ハッシュのみ照合する。
 * 生成は scripts/gen_auth_hash.py。正規化(trim+大文字化)・反復回数は両者で一致させること。
 * AUTH_VER を変えると全端末の localStorage の認証済み印が無効になり、再入力が求められる。 */
var PW_AUTH_KEY  = "peakweather2-auth",
    PW_AUTH_VER  = "2026b",
    PW_AUTH_SALT = "e4124b9719e30f22a006610d78b3fe31",
    PW_AUTH_HASH = "7348823df8e3bca69f7be53af9b9fc69e4f8bec7bcf60563d5573149d125e92a",
    PW_AUTH_ITER = 300000;

/* ---- ストレージアクセスの唯一の入口 ----
 * localStorage / sessionStorage は「値が保存できない」だけでなく、Safari の
 * 「すべてのCookieをブロック」・一部のプライベート閲覧・iframe 埋め込み等では
 * **アクセス自体が SecurityError を投げる**。素で呼ぶと、呼び出し元のスクリプトが
 * その行で丸ごと死ぬ(index.html は冒頭で sessionStorage を読むため画面が無反応になる)。
 *
 * 保存できない端末でもそのタブの間は使えるよう、メモリへフォールバックする
 * (次回訪問時に同意・認証の再入力が要るだけで済む)。
 * 読み書きは index.html / docs/find.html / docs/point.html すべてこの関数群を通すこと。 */
var pwMem = {}, pwSMem = {};
function pwLoad(k){ try{ var v=localStorage.getItem(k); if(v!=null)return v }catch(e){}
                    return k in pwMem ? pwMem[k] : null }
function pwSave(k,v){ pwMem[k]=v; try{ localStorage.setItem(k,v) }catch(e){} }
function pwDrop(k){ delete pwMem[k]; try{ localStorage.removeItem(k) }catch(e){} }
/* sessionStorage 版 (入口マーカー・山さがしの結果キャッシュ・座標ラベル用) */
function pwSLoad(k){ try{ var v=sessionStorage.getItem(k); if(v!=null)return v }catch(e){}
                     return k in pwSMem ? pwSMem[k] : null }
function pwSSave(k,v){ pwSMem[k]=v; try{ sessionStorage.setItem(k,v) }catch(e){} }
function pwSDrop(k){ delete pwSMem[k]; try{ sessionStorage.removeItem(k) }catch(e){} }

function pwIsAgreed(){ return pwLoad(PW_AGREE_KEY) === "1" }
function pwIsAuthed(){ return pwLoad(PW_AUTH_KEY) === PW_AUTH_VER }

/* ファイルをダウンロードしてローカルで直接開いた(file://)かどうか。
 * http://localhost 経由のローカル確認(python -m http.server)は http: なので対象外。 */
function pwIsLocalFile(){ return location.protocol === "file:" }

/* 操作を許可してよいか。規約同意・認証に加え、ローカルファイル直開きでないことが必要。
 * fail-closed: file:// で開いている限り、同意・認証が済んでいても常に false。 */
function pwGateOk(){ return !pwIsLocalFile() && pwIsAgreed() && pwIsAuthed() }

/* ---- ローカルファイル直開きの全画面ブロック ----
 * ダウンロードしたHTMLをそのまま開いて使われるのを防ぐ表示。pwGateOk()のfail-closedだけでも
 * 機能的には止まるが、非エンジニアにも分かるよう理由とオンライン版への導線を明示する。 */
function pwBlockLocalFile(){
  var ov = document.createElement("div");
  ov.className = "pwgate-localblock";
  ov.innerHTML =
    '<div class="pwgate-localblock-card">' +
      '<div class="pwgate-icon">🔒</div>' +
      '<h2>このファイルを直接開いてのご利用はできません</h2>' +
      '<p>お使いのファイルはダウンロードされたもので、パソコンやスマートフォンに保存して' +
      '直接開く形ではご利用いただけません。下記のオンライン版をご利用ください。</p>' +
      '<p class="pwgate-act"><a class="pwgate-btn" href="https://halab18.github.io/sangaku-yohou2/">' +
        'オンライン版を開く</a></p>' +
    '</div>';
  var st = document.createElement("style");
  st.textContent =
    ".pwgate-localblock{position:fixed;inset:0;z-index:2147483647;background:#f4f6fb;" +
      "display:flex;align-items:center;justify-content:center;padding:20px}" +
    ".pwgate-localblock-card{max-width:520px;padding:26px 22px;background:#fff;" +
      "border:1px solid #dee4ee;border-radius:12px;text-align:center;line-height:1.8}" +
    ".pwgate-localblock-card h2{margin:8px 0 12px;font-size:1.1em;color:#1e2d4a}" +
    ".pwgate-localblock-card p{margin:10px 0;font-size:.92em;color:#44506b;text-align:left}" +
    ".pwgate-localblock-card p.pwgate-act{text-align:center}";
  document.head.appendChild(st);
  document.body.appendChild(ov);
}
if(typeof document !== "undefined" && pwIsLocalFile()){
  document.addEventListener("DOMContentLoaded", pwBlockLocalFile);
}

/* 認証コードのハッシュ化。scripts/gen_auth_hash.py と同一パラメータを維持すること */
async function pwHashAuthCode(code){
  var norm = code.trim().toUpperCase(), enc = new TextEncoder();
  var key = await crypto.subtle.importKey("raw", enc.encode(norm), "PBKDF2", false, ["deriveBits"]);
  var bits = await crypto.subtle.deriveBits(
    {name:"PBKDF2", hash:"SHA-256", salt:enc.encode(PW_AUTH_SALT), iterations:PW_AUTH_ITER}, key, 256);
  return [].slice.call(new Uint8Array(bits)).map(function(b){return b.toString(16).padStart(2,"0")}).join("");
}

/* ---- サブページ用ガード (docs/find.html, docs/point.html) ----
 * 未同意・未認証なら <main> の中身を案内に差し替えて false を返す。
 * 呼び出し側はページ本体スクリプトの先頭で `if(!pwGuardPage())return;` とし、
 * イベント登録も外部APIの呼び出しも一切行わないこと (Open-Meteo の無料枠を守るのが本ゲートの目的)。
 * 認証UI自体はここには置かない — 入口をトップページに一本化し、認証の実装を1箇所に保つため。 */
function pwGuardPage(opts){
  if(pwGateOk())return true;
  var o = opts || {};
  var home = o.home || "../index.html";
  var main = document.querySelector("main") || document.body;
  main.innerHTML =
    '<div class="pwgate-block">' +
      '<div class="pwgate-icon">🔒</div>' +
      '<h2>このページのご利用には準備が必要です</h2>' +
      '<p>PeakWeather をご利用いただくには、トップページで<b>利用規約への同意</b>と' +
      '<b>認証コードの入力</b>をお願いしています' +
      '（気象データの無料利用枠を維持するためです。認証は端末ごとに初回の1回のみです）。</p>' +
      '<p class="pwgate-act"><a class="pwgate-btn" href="' + home + '">PeakWeather トップページへ</a></p>' +
      '<p class="pwgate-sub">認証がお済みの場合は、このページを再読み込みするとそのままご利用いただけます。</p>' +
    '</div>';
  var st = document.createElement("style");
  st.textContent =
    ".pwgate-block{max-width:560px;margin:26px auto;padding:22px 18px;background:#fff;" +
      "border:1px solid #dee4ee;border-radius:12px;text-align:center;line-height:1.8}" +
    ".pwgate-icon{font-size:2em;line-height:1}" +
    ".pwgate-block h2{margin:8px 0 12px;font-size:1.1em;color:#1e2d4a;border:0;padding:0}" +
    ".pwgate-block p{margin:10px 0;font-size:.9em;color:#44506b;text-align:left}" +
    ".pwgate-btn{display:inline-block;margin:8px auto 0;padding:12px 26px;background:#4276b5;" +
      "color:#fff;border-radius:10px;font-weight:700;text-decoration:none}" +
    ".pwgate-btn:hover{background:#3a68a3}" +
    ".pwgate-block p.pwgate-act{text-align:center}" +
    ".pwgate-sub{font-size:.82em!important;color:#8a94a8!important}";
  document.head.appendChild(st);
  return false;
}

/* ---- GA4 イベント送信の薄いラッパ ----
 * gtag.js は async 読み込みのため、広告ブロッカーや読み込み前の呼び出しで
 * 未定義になりうる。計測の失敗がアプリの動作を壊さないよう必ずここを通す。 */
function pwTrack(name, params){
  try{ if(typeof gtag === "function") gtag("event", name, params || {}) }catch(e){}
}
