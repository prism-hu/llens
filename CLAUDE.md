# LLENS - Large Language Enhanced Nexus System

北大病院内 HGX H200x8 LLM 推論基盤。

## 環境

- デプロイまではオンライン。デプロイ後は病院内閉域に閉ざされる
- 取り出すには SSD 初期化が必要。データの持ち出し不可
- 閉域後の更新は基本的に行わない

## サーバー

- HGX H200 x8 (141GB HBM3e/基、計 1,128GB)
- Ubuntu 24.04 LTS
- NVIDIA ドライバ + Docker インストール済み

## スタック

- **SGLang**: uv 直接実行。コンテナ化しない
- **Open WebUI**: Docker で動作。ユーザー管理もここで行う
- **モデル**: `models/` 配下 (gitignored)。構成は変わりうる

(公開ポート・公開範囲は DEPLOYMENT.md の単一情報源を参照)

## 運用ユーザー

- 現在は `enda` ユーザー (管理者) でそのまま実行
- サーバーに SSH するのは基本 enda のみ。`user` はテスト用
- 将来的には専用サービスユーザー `llens` + `/opt/llens` 構成に移行予定 (docs/migration.md 参照)

## リポジトリ構成

- `scripts/llm/sglang-*.sh` — モデルごとの SGLang 起動スクリプト
- `scripts/owui/{backup,restore,wal-flush}.sh` — Open WebUI 運用
- `scripts/preflight/{audit,apply,scan}.sh` — 院内搬入前の構成適用 / ClamAV
- `owui/{filters,tools,skills}` — OWUI 投入用の独自ロジック。OWUI イメージ自体も `docker/open-webui/` で自前ビルド (stock image そのままではない)
- `Makefile` — 起動・preflight 等の運用ターゲット (一覧は `make help`)
- `docker-compose.yml` — OWUI と周辺サービス (監視等)
- `DEPLOYMENT.md` — デプロイ運用・ホスト公開範囲・UFW ルール・緊急対応 (ネットワーク/FW の単一情報源)
- `docs/migration.md` — 本番移行メモ (systemd、専用ユーザー等)
- モデル情報 (スペック、VRAM、起動コマンド) は README のモデルセクションに記載

## 方針

- モデル構成は試行錯誤する。システム基盤 (SGLang + Open WebUI + H200x8) は不変
- 基盤はデフォルト寄りで余計な独自設定を足さない。ただし `scripts/llm/sglang-*.sh` のモデル別フラグ (context-length・spec decoding 等) は意図的チューニングなので剥がさない
- 過度な設計をしない。段階的に進める
