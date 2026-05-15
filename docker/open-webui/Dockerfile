# LLENS 用 Open WebUI イメージ
#
# 上流 OWUI に PDF → 画像変換と PDF メタデータ抽出のための依存を追加。
# 用途: OWUI filter で PDF を page 画像化して VLM (Kimi K2.6 MoonViT 等) に送る経路。
# Docling は構造化テキスト抽出に特化しているため、医療文書の図表・スキャン PDF を
# 拾うために VLM 経由も併用する設計。
#
# バージョン更新時は FROM タグと docker-compose.yml の image タグを同期して
#   docker compose build --pull open-webui
# で再ビルド。

FROM ghcr.io/open-webui/open-webui:v0.9.5

RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        pdf2image==1.17.0 \
        pypdf==6.7.5
