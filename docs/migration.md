# 本番移行メモ

現在は enda ユーザーで直接実行しているが、本番運用に向けて以下を検討。

## 専用サービスユーザー

```bash
useradd --system --shell /usr/sbin/nologin --home-dir /opt/llens --create-home llens
usermod -aG video,render llens
```

- `video`,`render` グループで GPU アクセスを付与
- `/dev/nvidia*` のグループは `ls -la /dev/nvidia*` で要確認
- 動作確認: `sudo -u llens nvidia-smi`

## デプロイパス

`/opt/llens` に配置し `llens:llens` で所有。
管理者は sudo 経由で操作: `sudo -u llens uv sync` 等。

## systemd ユニット (vLLM)

```ini
[Unit]
Description=LLens vLLM Inference Server
After=network.target nvidia-persistenced.service
Requires=nvidia-persistenced.service

[Service]
Type=exec
User=llens
Group=llens
WorkingDirectory=/opt/llens
ExecStart=/usr/local/bin/uv run vllm serve ./models/GLM-5-FP8 \
  --tensor-parallel-size 8 \
  --gpu-memory-utilization 0.85 \
  --speculative-config.method mtp \
  --speculative-config.num_speculative-tokens 1 \
  --tool-call-parser glm47 \
  --reasoning-parser glm45 \
  --enable-auto-tool-choice \
  --served-model-name glm-5 \
  --host 0.0.0.0 \
  --port 8000
Restart=on-failure
RestartSec=10
Environment=HOME=/opt/llens

[Install]
WantedBy=multi-user.target
```

- uv をシステムワイドに配置: `/usr/local/bin/uv`
- `nvidia-persistenced.service` 依存で GPU 初期化後に起動
- `Restart=on-failure` でクラッシュ時自動復帰

## Open WebUI (Docker)

Docker の `restart: unless-stopped` ポリシーで自動復帰。
`systemctl enable docker` で Docker デーモン自体の自動起動を保証。
別途 systemd ユニットは不要。

## デプロイフロー

```
1. OS インストール (Ubuntu 24.04 LTS)
2. SSH ログイン
3. git clone → /opt/llens に配置
4. NVIDIA ドライバ, Docker, uv インストール
5. 再起動 (ドライバ反映)
6. llens ユーザー作成
7. モデルダウンロード (オンライン中)
8. uv sync, systemd 登録, サービス起動
9. 動作確認
10. 閉域接続
```

## 検証

```bash
sudo -u llens nvidia-smi
curl http://localhost:8000/v1/models
curl -s http://localhost:3000 | head -1
sudo reboot  # 再起動後に全サービス自動復帰を確認
```
