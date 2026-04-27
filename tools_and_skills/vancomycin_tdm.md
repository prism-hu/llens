---
name: vancomycin-tdm
description: "バンコマイシン血中濃度モニタリング (TDM) における AUC₂₄推定、濃度-時間曲線の可視化、用量調整提案のワークフロー。利用者から「バンコマイシン TDM」「バンコの濃度評価」「ピーク/トラフ」「AUC₂₄」「バンコの投与量どうしよう」等の相談を受けた時に起動する。tool は使わず、Pyodide (Code Interpreter) で計算・プロットを行う。北大病院では薬剤部のTDM支援サービスが標準窓口であり、本SKILLは初期評価・教育・What-if検討の補助に位置づける。"
---

# バンコマイシン TDM ワークフロー

## 位置づけ

北大病院では薬剤部の TDM 支援サービスが標準窓口です。本SKILLは以下の補助用途:

- 利用者 (医師) が**初期評価**として AUC₂₄ をざっと知りたい時
- **教育目的**で濃度-時間曲線の意味を見たい時
- 用量変更の **What-if** を試したい時

精度の高い予測 (ベイズ推定、母集団薬物動態モデル) や正式な投与量提案は薬剤部のTDM支援サービスに委ねる旨を、回答の最後に必ず添えること。

## ワークフロー

### Step 1: 必要情報の聴取

以下を順に確認する。**全部一気に聞かない** (情報が多すぎると医師が嫌がる)。揃っているものは省略可。

**最低限必要な情報**:
1. 採血値: ピーク濃度 (mg/L)、トラフ濃度 (mg/L)
2. 採血タイミング:
   - 何回目の投与での採血か (定常状態 = 第4回投与以降が望ましい)
   - ピーク採血: 点滴終了から何時間後か (通常1時間後)
   - トラフ採血: 次回投与の何時間前か (通常 直前または30分前)
3. 現在のレジメン: 1回投与量 (mg)、投与間隔 (hours)、点滴時間 (通常1時間)

**あると望ましい情報** (用量提案の精度を上げるため):
4. 患者背景: 体重、年齢、性別、Cr (eGFR)
5. 適応: MRSA菌血症? 髄膜炎? 等 (目標AUC₂₄が変わる可能性)
6. MIC値が出ていれば (出ていなければ MIC=1 mg/L 仮定)

### Step 2: 計算 (Pyodide で実行)

以下のPythonコードを Code Interpreter で実行する。

```python
import math
import matplotlib.pyplot as plt
import numpy as np
import io, base64

# ===== 入力 (聴取した値で書き換える) =====
trough_mg_l = 15.0       # トラフ濃度 (mg/L)
peak_mg_l = 30.0         # ピーク濃度 (mg/L)
dose_mg = 1000           # 1回投与量 (mg)
dosing_interval_h = 12   # 投与間隔 (h)
infusion_duration_h = 1.0
time_peak_after_infusion_end_h = 1.0   # 点滴終了からpeak採血までの時間
time_trough_before_next_dose_h = 0.5   # 次回投与のtrough採血何時間前か
mic_mg_l = 1.0           # MIC (不明なら1.0仮定)

# ===== 1区画モデルでの薬物動態パラメタ推定 =====
# 採血間の経過時間
t_peak = infusion_duration_h + time_peak_after_infusion_end_h
t_trough = dosing_interval_h - time_trough_before_next_dose_h
delta_t = t_trough - t_peak

if peak_mg_l <= trough_mg_l:
    raise ValueError("ピーク濃度がトラフ濃度以下です。採血タイミングを確認してください。")
if delta_t <= 0:
    raise ValueError("採血タイミングが矛盾しています。")

# 消失速度定数 ke、半減期
ke = math.log(peak_mg_l / trough_mg_l) / delta_t
half_life = math.log(2) / ke

# 真のCmax (点滴終了時) と Cmin (次回投与直前) を外挿
c_max_true = peak_mg_l * math.exp(ke * time_peak_after_infusion_end_h)
c_min_true = trough_mg_l * math.exp(-ke * time_trough_before_next_dose_h)

# AUC_tau (1投与間隔のAUC)
# 点滴中: 0 → c_max_true への線形上昇 (近似)
# 消失相: c_max_true → c_min_true の指数減衰
auc_infusion_phase = infusion_duration_h * c_max_true / 2
auc_elim_phase = (c_max_true - c_min_true) / ke
auc_tau = auc_infusion_phase + auc_elim_phase
auc24 = auc_tau * (24 / dosing_interval_h)

# AUC₂₄/MIC
auc_mic_ratio = auc24 / mic_mg_l

# ===== 評価 =====
if auc_mic_ratio < 400:
    assessment = "subtherapeutic"
    recommendation = "増量を検討 (TDM支援サービスへ相談推奨)"
elif auc_mic_ratio <= 600:
    assessment = "therapeutic"
    recommendation = "現用量を継続"
else:
    assessment = "potentially toxic"
    recommendation = "腎毒性リスク、減量を検討 (TDM支援サービスへ相談推奨)"

print(f"=== 薬物動態パラメタ ===")
print(f"消失速度定数 ke = {ke:.4f} /h")
print(f"半減期 = {half_life:.2f} h")
print(f"外挿 Cmax (点滴終了時) = {c_max_true:.2f} mg/L")
print(f"外挿 Cmin (次回投与直前) = {c_min_true:.2f} mg/L")
print(f"")
print(f"=== AUC評価 ===")
print(f"AUC_tau (1投与間隔) = {auc_tau:.1f} mg·h/L")
print(f"AUC₂₄ = {auc24:.1f} mg·h/L")
print(f"AUC₂₄/MIC = {auc_mic_ratio:.0f} (MIC={mic_mg_l} mg/L 想定)")
print(f"評価: {assessment}")
print(f"提案: {recommendation}")

# ===== プロット =====
plt.figure(figsize=(10, 6))

# 1投与間隔の濃度-時間曲線
t_inf = np.linspace(0, infusion_duration_h, 50)
c_inf = c_max_true * (t_inf / infusion_duration_h)  # 点滴中の線形近似
t_elim = np.linspace(infusion_duration_h, dosing_interval_h, 200)
c_elim = c_max_true * np.exp(-ke * (t_elim - infusion_duration_h))

t_all = np.concatenate([t_inf, t_elim])
c_all = np.concatenate([c_inf, c_elim])
plt.plot(t_all, c_all, 'b-', linewidth=2, label='Predicted concentration')

# 目標域 (AUC₂₄ 400-600 に対応する平均濃度の目安: 16.7-25 mg/L)
plt.axhspan(400/24, 600/24, alpha=0.2, color='green', label=f'Target Cavg ({400/24:.1f}-{600/24:.1f} mg/L for AUC₂₄ 400-600)')

# 採血点
plt.plot(t_peak, peak_mg_l, 'ro', markersize=10, label=f'Peak measured: {peak_mg_l} mg/L')
plt.plot(t_trough, trough_mg_l, 'go', markersize=10, label=f'Trough measured: {trough_mg_l} mg/L')

# 外挿点
plt.plot(infusion_duration_h, c_max_true, 'r^', markersize=8, alpha=0.5, label=f'Cmax extrapolated: {c_max_true:.1f}')
plt.plot(dosing_interval_h, c_min_true, 'g^', markersize=8, alpha=0.5, label=f'Cmin extrapolated: {c_min_true:.1f}')

plt.xlabel('Time after dose start (hours)')
plt.ylabel('Concentration (mg/L)')
plt.title(f'Vancomycin concentration-time curve\n'
          f'{dose_mg} mg q{int(dosing_interval_h)}h | AUC₂₄ = {auc24:.0f} mg·h/L | t₁/₂ = {half_life:.1f} h | {assessment}')
plt.legend(loc='upper right', fontsize=9)
plt.grid(True, alpha=0.3)
plt.xlim(0, dosing_interval_h)
plt.ylim(0, max(c_max_true, peak_mg_l) * 1.2)

# OpenWebUI 表示規則に従い base64 で出力
buf = io.BytesIO()
plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
buf.seek(0)
print(f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}")
plt.close()
```

### Step 3: 結果の解釈と提示

1. **数値結果を表で提示**: AUC₂₄、半減期、外挿Cmax/Cmin、評価
2. **濃度-時間曲線**: プロットを表示
3. **臨床的解釈**:
   - 目標域 (AUC₂₄ 400-600) に対する位置づけ
   - 半減期から見た投与間隔の妥当性 (半減期の2-3倍が標準的な投与間隔)
   - 外れている場合の方向性 (用量変更 or 間隔変更のどちらが妥当か簡潔に)
4. **薬剤部TDM支援への誘導**: 用量変更を実施する場合は薬剤部 TDM 支援サービスへの相談を推奨

### Step 4: What-if 検討 (求められた場合)

利用者から「用量を1.5gにしたら?」「q8hに短縮したら?」と聞かれたら、Step 2のコードを編集して再実行する。Pyodide なので何度でも繰り返せる。

What-if時の予測式:
- 同じ患者の ke、Vd は変わらない (推定済み) と仮定
- 新しい dose、interval を入れて新しいAUC₂₄を計算
- ke と Vd は前回の計算結果から取得

```python
# 前回の ke を流用、新しいレジメンで予測
new_dose = 1500
new_interval = 12

# Vd を推定 (簡易): Vd = Dose / [ke × infusion_duration × Cmax_true × (1 - e^(-ke×infusion))]
# より正確には: AUC_tau = Dose / CL、CL = ke × Vd
cl = dose_mg / auc_tau   # 既知レジメンから CL を逆算
new_auc_tau = new_dose / cl
new_auc24 = new_auc_tau * (24 / new_interval)
print(f"What-if: {new_dose}mg q{new_interval}h → AUC₂₄ ≈ {new_auc24:.0f} mg·h/L")
```

## 注意事項

### 必須の注記事項

回答の最後に必ず以下を添える:

1. **本値は2点採血法による簡易推定**であり、ベイズ推定 (PrecisePK等) と比べて精度が劣る
2. **定常状態 (通常 第4回投与以降) での採血を前提**。それ以前のデータでは推定が大きくずれる
3. **MIC=1 mg/L 想定**で評価。MRSAで MIC≥2 の場合は目標AUC₂₄ も上がる
4. **正式な投与量変更は薬剤部 TDM 支援サービスへ相談**を推奨

### 落とし穴

- **採血タイミングの矛盾**: ピーク採血が点滴終了直後すぎる、トラフ採血が次回投与から離れすぎている等は推定誤差の元。利用者に採血時刻を確認する
- **腎機能の急変**: 計算は採血時点の状態を反映するが、腎機能が急変中の患者では予測が当たらない。Crトレンドを利用者に確認する
- **持続投与 vs 間欠投与**: 本SKILLは間欠投与 (q8h、q12h等) 前提。持続投与 (continuous infusion) は別の式が必要
- **小児・妊婦・透析患者**: 本SKILLの式は成人非透析患者前提。これらの集団では薬剤部TDM必須

### 用量調整の方針 (一般論)

- AUC₂₄ < 400: 用量増量を優先 (間隔短縮よりも)
- AUC₂₄ > 600 + trough 高値: 間隔延長を優先
- AUC₂₄ > 600 + trough 正常 + Cmax 高値: 1回量減量
- 半減期 < 4h: 投与間隔短縮 (q8h検討)
- 半減期 > 12h: 投与間隔延長 (q24h検討)、腎機能要確認

ただし**確定的な投与量は北海道大学病院薬剤部TDM支援に委ねる**。本SKILLは方向性の提示まで。

## 北海道大学病院薬剤部

- 内線: 5685

## その他フィードバック

- メール: prism-hu-office@pop.med.hokudai.ac.jp
- 内線: 5352
