.PHONY: help \
        run-ds3 run-ds4 run-glm run-kimi run-qwen \
        preflight-audit preflight-apply preflight-scan

help:
	@echo "推論サーバ起動 (前面実行 — Ctrl+C で停止):"
	@echo "  make run-ds3           - DeepSeek V3.2   (sglang)"
	@echo "  make run-ds4           - DeepSeek V4 Pro (sglang)"
	@echo "  make run-glm           - GLM-5.1         (sglang)"
	@echo "  make run-kimi          - Kimi K2.6       (sglang)"
	@echo "  make run-qwen          - Qwen3.5         (sglang)"
	@echo ""
	@echo "搬入前作業 (preflight):"
	@echo "  make preflight-audit   - 現状確認 (read-only、いつでも何度でも)"
	@echo "  make preflight-apply   - 不要設定 omit + 構成適用 (idempotent)"
	@echo "  make preflight-scan    - ClamAV 全体スキャン (シャットダウン直前)"
	@echo ""
	@echo "ログ出力先: logs/"

# ----- 推論サーバ起動 -----
run-ds3:
	bash scripts/llm/sglang-deepseek-v3.2.sh

run-ds4:
	bash scripts/llm/sglang-deepseek-v4-pro.sh

run-glm:
	bash scripts/llm/sglang-glm5.1.sh

run-kimi:
	bash scripts/llm/sglang-kimi-k2.6.sh

run-qwen:
	bash scripts/llm/sglang-qwen3.5.sh

# ----- 搬入前作業 -----
preflight-audit:
	sudo bash scripts/preflight/audit.sh

preflight-apply:
	sudo bash scripts/preflight/apply.sh

preflight-scan:
	sudo bash scripts/preflight/scan.sh
