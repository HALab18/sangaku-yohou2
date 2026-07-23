#!/usr/bin/env python3
"""認証コードのハッシュ生成ツール(年次更新用)。

PeakWeather Web版(index.html)の認証ゲートに埋め込む定数を生成する。
コード本体はリポジトリに残さないこと(公開リポジトリのため)。
YAMAPモーメント(閲覧許可制)にのみ記載する。

使い方:
    python scripts/gen_auth_hash.py              # 7文字コードを自動生成
    python scripts/gen_auth_hash.py --code ABC2345  # コードを指定してハッシュ化

出力の3定数(AUTH_VER/AUTH_SALT/AUTH_HASH)を index.html の同名定数と差し替えると
全利用者が再入力を求められる(localStorageの認証済み印がバージョン不一致になるため)。

※JS側(index.html の verifyAuthCode)と完全に同一パラメータであること:
   - 正規化: trim + 大文字化
   - PBKDF2-HMAC-SHA256 / 反復 300000 回 / ソルトはUTF-8文字列 / 出力32バイトのhex
  片方だけ変えると認証が通らなくなる。
"""
import argparse
import datetime
import hashlib
import secrets
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# 紛らわしい文字(0/O, 1/I/L)を除いた大文字英数字
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 7
ITERATIONS = 300000  # index.html の AUTH_ITER と一致させる


def gen_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def main():
    ap = argparse.ArgumentParser(description="認証コードのハッシュ生成")
    ap.add_argument("--code", help="コードを指定(省略時は自動生成)")
    ap.add_argument("--ver", help="AUTH_VERを指定(省略時は今日の西暦年。同年内の再更新等に)")
    args = ap.parse_args()

    code = args.code if args.code else gen_code()
    norm = code.strip().upper()  # JS側と同じ正規化
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", norm.encode("utf-8"), salt.encode("utf-8"), ITERATIONS
    ).hex()
    ver = args.ver if args.ver else str(datetime.date.today().year)

    print(f"認証コード(YAMAPモーメントにのみ記載。リポジトリに残さない): {code}")
    print()
    print("index.html に貼る定数(既存の3定数と差し替え):")
    print(f'const AUTH_VER="{ver}",')
    print(f'      AUTH_SALT="{salt}",')
    print(f'      AUTH_HASH="{digest}";')


if __name__ == "__main__":
    main()
