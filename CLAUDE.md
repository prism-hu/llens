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

- **vLLM**: uv 直接実行。コンテナ化しない。`:8000`
- **Open WebUI**: Docker で動作。`:3000`。ユーザー管理もここで行う
- **モデル**: `models/` 配下 (gitignored)。構成は変わりうる

## 運用ユーザー

- 現在は `enda` ユーザー (管理者) でそのまま実行
- サーバーに SSH するのは基本 enda のみ。`user` はテスト用
- 将来的には専用サービスユーザー `llens` + `/opt/llens` 構成に移行予定 (docs/migration.md 参照)

## リポジトリ構成

- `scripts/vllm-*.sh` — モデルごとの vLLM 起動スクリプト。systemd の ExecStart にも使える
- `docker-compose.yml` — Open WebUI
- `docs/migration.md` — 本番移行メモ (systemd、専用ユーザー等)
- モデル情報 (スペック、VRAM、起動コマンド) は README のモデルセクションに記載

## 方針

- モデル構成は試行錯誤する。システム基盤 (vLLM + Open WebUI + H200x8) は不変
- デフォルト値をそのまま使う。独自設定を入れない
- 過度な設計をしない。段階的に進める
