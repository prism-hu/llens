"""
title: Medical Calculator
author: Ken Enda
version: 0.1
description: 臨床で頻用される、手計算が煩雑かつ誤りやすい医学計算・スコアリングツール。
             使い方の詳細は SKILL 側で取り出すこと。
requirements:
"""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class Tools:
    """医療計算ツール群。すべて prefix `calc_` で統一。

    対象: 算術モジュール任せでは精度が出ない、または式の分岐や閾値判定が
    複雑で手計算ミスが起きやすいもののみ。BMI / BSA / 補正Ca / A-aDO2 等の
    単純な式は本ツールには含めない（モデル側の算術で十分）。
    """

    class Valves(BaseModel):
        # 現状外部依存なし。将来 reference range や施設標準式の差し替えに備えて確保。
        institution_egfr_default: str = Field(
            default="ckdepi_2021",
            description="eGFRのデフォルト式 (ckdepi_2021 / jsn / mdrd)",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    # =========================================================================
    # 腎機能
    # =========================================================================

    def calc_egfr_ckdepi2021(
        self,
        cr: float,
        age: int,
        sex: Literal["M", "F"],
        japanese_coefficient: bool = False,
    ) -> Dict[str, Any]:
        """CKD-EPI 2021式によるeGFRを計算する (mL/min/1.73m²)。

        :param cr: 血清クレアチニン (mg/dL)
        :param age: 年齢 (歳)
        :param sex: "M" または "F"
        :param japanese_coefficient: 日本人補正係数 (×0.813) を適用するか
        :return: {egfr, formula, japanese_coefficient_applied, ckd_stage}
        """
        # CKD-EPI 2021 (race-free)
        if sex == "F":
            kappa, alpha, sex_factor = 0.7, -0.241, 1.012
        else:
            kappa, alpha, sex_factor = 0.9, -0.302, 1.0
        ratio = cr / kappa
        egfr = (
            142
            * (min(ratio, 1) ** alpha)
            * (max(ratio, 1) ** -1.200)
            * (0.9938 ** age)
            * sex_factor
        )
        if japanese_coefficient:
            egfr *= 0.813

        # CKDステージ判定
        if egfr >= 90:
            stage = "G1"
        elif egfr >= 60:
            stage = "G2"
        elif egfr >= 45:
            stage = "G3a"
        elif egfr >= 30:
            stage = "G3b"
        elif egfr >= 15:
            stage = "G4"
        else:
            stage = "G5"

        return {
            "egfr": round(egfr, 1),
            "unit": "mL/min/1.73m²",
            "formula": "CKD-EPI 2021 (race-free)",
            "japanese_coefficient_applied": japanese_coefficient,
            "ckd_stage": stage,
        }

    def calc_ccr_cockcroft_gault(
        self,
        cr: float,
        age: int,
        sex: Literal["M", "F"],
        weight_kg: float,
    ) -> Dict[str, Any]:
        """Cockcroft-Gault式によるクレアチニンクリアランス (mL/min) を計算する。
        薬剤投与量調整に用いる。体表面積補正は行わない (絶対値)。

        :param cr: 血清クレアチニン (mg/dL)
        :param age: 年齢 (歳)
        :param sex: "M" または "F"
        :param weight_kg: 体重 (kg)。肥満例では IBW または AdjBW の使用を検討すること。
        :return: {ccr, unit, formula, note}
        """
        ccr = ((140 - age) * weight_kg) / (72 * cr)
        if sex == "F":
            ccr *= 0.85
        return {
            "ccr": round(ccr, 1),
            "unit": "mL/min",
            "formula": "Cockcroft-Gault",
            "note": (
                "体表面積補正なし。薬剤投与量調整に用いる場合は本値を使用する。"
                "肥満例 (BMI≥30) では実体重ではなく IBW あるいは AdjBW での"
                "再計算を検討すること。"
            ),
        }

    # =========================================================================
    # 肝
    # =========================================================================

    def calc_meld_na(
        self,
        bilirubin: float,
        cr: float,
        inr: float,
        na: float,
        dialysis_2x_in_last_week: bool = False,
    ) -> Dict[str, Any]:
        """MELD-Na スコアを計算する (移植適応評価等)。

        :param bilirubin: 総ビリルビン (mg/dL)
        :param cr: 血清クレアチニン (mg/dL)。透析時は 4.0 にクリップ。
        :param inr: PT-INR
        :param na: 血清Na (mEq/L)。125-137の範囲にクリップ。
        :param dialysis_2x_in_last_week: 過去7日以内に2回以上の透析または24h CRRT
        :return: {meld, meld_na, components}
        """
        import math

        # 各値の下限クリップ (1.0未満は1.0として扱う)
        bili = max(bilirubin, 1.0)
        inr_c = max(inr, 1.0)
        cr_c = max(cr, 1.0)
        if dialysis_2x_in_last_week or cr >= 4.0:
            cr_c = 4.0

        meld = (
            0.957 * math.log(cr_c)
            + 0.378 * math.log(bili)
            + 1.120 * math.log(inr_c)
            + 0.643
        ) * 10
        meld = round(meld)
        meld = max(6, min(meld, 40))

        # MELD-Na (UNOS 2016式)
        na_c = max(125, min(na, 137))
        if meld > 11:
            meld_na = meld + 1.32 * (137 - na_c) - (0.033 * meld * (137 - na_c))
            meld_na = round(meld_na)
            meld_na = max(6, min(meld_na, 40))
        else:
            meld_na = meld

        return {
            "meld": meld,
            "meld_na": meld_na,
            "components": {
                "bilirubin_used": bili,
                "cr_used": cr_c,
                "inr_used": inr_c,
                "na_used": na_c,
                "dialysis_adjustment_applied": dialysis_2x_in_last_week or cr >= 4.0,
            },
            "note": "UNOS 2016 MELD-Na式。MELD≤11ではMELD-Na=MELDとなる。",
        }

    def calc_albi_grade(
        self,
        albumin_g_dl: float,
        bilirubin_mg_dl: float,
    ) -> Dict[str, Any]:
        """ALBI score / grade を計算する (肝予備能評価、HCC等で頻用)。

        :param albumin_g_dl: アルブミン (g/dL)
        :param bilirubin_mg_dl: 総ビリルビン (mg/dL)
        :return: {albi_score, albi_grade, note}
        """
        import math

        # ALBIは bilirubin µmol/L, albumin g/L で定義されているため単位変換
        bili_umol = bilirubin_mg_dl * 17.1
        alb_g_l = albumin_g_dl * 10
        albi = math.log10(bili_umol) * 0.66 + alb_g_l * (-0.085)

        if albi <= -2.60:
            grade = 1
        elif albi <= -1.39:
            grade = 2
        else:
            grade = 3

        return {
            "albi_score": round(albi, 3),
            "albi_grade": grade,
            "note": (
                "Grade 1: 最良 (中央値 OS 18.5-85.6ヶ月), "
                "Grade 2: 中間, "
                "Grade 3: 最不良 (中央値 OS 5.3-6.2ヶ月)。"
            ),
        }

    def calc_fib4(
        self,
        ast: float,
        alt: float,
        plt_10e4_per_ul: float,
        age: int,
    ) -> Dict[str, Any]:
        """FIB-4 indexを計算する (慢性肝疾患の線維化スクリーニング)。

        :param ast: AST (U/L)
        :param alt: ALT (U/L)。0は不可。
        :param plt_10e4_per_ul: 血小板数 (×10^4/µL)。日本表記。
        :param age: 年齢 (歳)
        :return: {fib4, interpretation, note}

        注意: 慢性肝炎 (HCV/HBV/NAFLD) の線維化スクリーニング目的。
              急性肝障害には適用しない。
        """
        import math

        # 日本表記 (×10^4/µL) → 米国表記 (×10^9/L) は同値 (×10^4/µL = ×10/nL = ×10^9/L*0.01)
        # FIB-4は分母 PLT(×10^9/L) で定義。1×10^4/µL = 10×10^9/L → ×10
        plt_10e9_l = plt_10e4_per_ul * 10
        if plt_10e9_l == 0 or alt <= 0:
            return {"error": "PLTおよびALTは正値である必要がある"}

        fib4 = (age * ast) / (plt_10e9_l * math.sqrt(alt))

        # 65歳未満と以上で閾値が異なる (NAFLD)
        if age < 65:
            low, high = 1.30, 2.67
        else:
            low, high = 2.0, 2.67

        if fib4 < low:
            interp = "low_risk (進行線維化の可能性低い)"
        elif fib4 < high:
            interp = "indeterminate (追加評価が望ましい)"
        else:
            interp = "high_risk (進行線維化の可能性、専門医紹介を考慮)"

        return {
            "fib4": round(fib4, 2),
            "interpretation": interp,
            "thresholds_used": {"low": low, "high": high, "age_group": "<65" if age < 65 else "≥65"},
            "note": "慢性肝炎 (HCV/HBV/NAFLD) のスクリーニング指標。急性肝障害には不適。",
        }

    # =========================================================================
    # 集中治療 / 救急
    # =========================================================================

    def calc_apache2(
        self,
        # APS (Acute Physiology Score) 12項目
        temp_c: float,
        map_mmhg: float,
        hr: int,
        rr: int,
        fio2: float,
        pao2: Optional[float] = None,
        a_ado2: Optional[float] = None,
        ph: float = 7.40,
        na: float = 140,
        k: float = 4.0,
        cr_mg_dl: float = 1.0,
        acute_renal_failure: bool = False,
        hct: float = 40,
        wbc_10e3_ul: float = 8.0,
        gcs: int = 15,
        # 年齢
        age: int = 50,
        # 慢性疾患
        chronic_organ_failure: bool = False,
        admission_type: Literal[
            "non_op", "emergency_post_op", "elective_post_op"
        ] = "non_op",
    ) -> Dict[str, Any]:
        """APACHE II スコアを計算する (ICU入室時24時間以内の最悪値で算出)。

        :param temp_c: 体温 (℃、直腸温が標準)
        :param map_mmhg: 平均動脈圧 (mmHg)
        :param hr: 心拍数 (/min)
        :param rr: 呼吸数 (/min)
        :param fio2: 吸入酸素濃度 (0.21-1.0)
        :param pao2: PaO2 (mmHg)。FiO2<0.5の時に使用。
        :param a_ado2: A-aDO2 (mmHg)。FiO2≥0.5の時に使用。
        :param ph: 動脈血pH (HCO3代用なら別途代用スコアあり、本実装はpH優先)
        :param na: 血清Na (mEq/L)
        :param k: 血清K (mEq/L)
        :param cr_mg_dl: 血清Cr (mg/dL)
        :param acute_renal_failure: 急性腎不全 (Crスコアが2倍になる)
        :param hct: ヘマトクリット (%)
        :param wbc_10e3_ul: 白血球数 (×10³/µL)
        :param gcs: GCS合計
        :param age: 年齢 (歳)
        :param chronic_organ_failure: 重度慢性臓器不全または免疫不全あり
        :param admission_type: 入室区分
        :return: {apache2, aps, age_points, chronic_health_points, mortality_estimate, breakdown}
        """
        # --- APS 各項目のスコアリング ---
        def score_temp(t):
            if t >= 41 or t < 30: return 4
            if t >= 39 or t < 32: return 3
            if t < 34: return 2
            if t >= 38.5 or t < 36: return 1
            return 0

        def score_map(m):
            if m >= 160 or m <= 49: return 4
            if m >= 130: return 3
            if m >= 110 or m <= 69: return 2
            return 0

        def score_hr(h):
            if h >= 180 or h <= 39: return 4
            if h >= 140 or h <= 54: return 3
            if h >= 110 or h <= 69: return 2
            return 0

        def score_rr(r):
            if r >= 50 or r <= 5: return 4
            if r >= 35: return 3
            if r <= 9: return 2
            if r >= 25 or r <= 11: return 1
            return 0

        def score_oxy(fio2_, pao2_, aado2_):
            if fio2_ >= 0.5:
                if aado2_ is None:
                    return None  # 呼べない
                if aado2_ >= 500: return 4
                if aado2_ >= 350: return 3
                if aado2_ >= 200: return 2
                return 0
            else:
                if pao2_ is None:
                    return None
                if pao2_ < 55: return 4
                if pao2_ < 60: return 3
                if pao2_ < 70: return 1
                return 0

        def score_ph(p):
            # APACHE II 原典 (Knaus 1985) のpHスコア表
            # ≥7.70:4, 7.60-7.69:3, 7.50-7.59:1, 7.33-7.49:0,
            # 7.25-7.32:2, 7.15-7.24:3, <7.15:4
            if p >= 7.70 or p < 7.15: return 4
            if p >= 7.60 or p < 7.25: return 3
            if p < 7.33: return 2
            if p >= 7.50: return 1
            return 0

        def score_na(n):
            if n >= 180 or n <= 110: return 4
            if n >= 160 or n <= 119: return 3
            if n >= 155 or n <= 129: return 2
            if n >= 150: return 1
            return 0

        def score_k(kk):
            if kk >= 7 or kk < 2.5: return 4
            if kk >= 6: return 3
            if 2.5 <= kk < 3.0: return 2
            if kk >= 5.5 or kk < 3.5: return 1
            return 0

        def score_cr(c, arf):
            base = 0
            if c >= 3.5: base = 4
            elif c >= 2: base = 3
            elif c >= 1.5: base = 2
            elif c < 0.6: base = 2
            else: base = 0
            return base * 2 if arf else base

        def score_hct(h):
            if h >= 60 or h < 20: return 4
            if h >= 50 or h < 30: return 2
            if h >= 46: return 1
            return 0

        def score_wbc(w):
            if w >= 40 or w < 1: return 4
            if w >= 20 or w < 3: return 2
            if w >= 15: return 1
            return 0

        def score_age(a):
            if a >= 75: return 6
            if a >= 65: return 5
            if a >= 55: return 3
            if a >= 45: return 2
            return 0

        def score_chronic(ch, atype):
            if not ch:
                return 0
            return 5 if atype == "non_op" or atype == "emergency_post_op" else 2

        oxy = score_oxy(fio2, pao2, a_ado2)
        if oxy is None:
            return {
                "error": (
                    "酸素化スコアを計算できない: FiO2≥0.5の場合は a_ado2 を、"
                    "FiO2<0.5の場合は pao2 を指定してください。"
                )
            }

        breakdown = {
            "temp": score_temp(temp_c),
            "map": score_map(map_mmhg),
            "hr": score_hr(hr),
            "rr": score_rr(rr),
            "oxygenation": oxy,
            "ph": score_ph(ph),
            "na": score_na(na),
            "k": score_k(k),
            "cr": score_cr(cr_mg_dl, acute_renal_failure),
            "hct": score_hct(hct),
            "wbc": score_wbc(wbc_10e3_ul),
            "gcs_points": 15 - gcs,
        }
        aps = sum(breakdown.values())
        age_points = score_age(age)
        chronic_points = score_chronic(chronic_organ_failure, admission_type)
        total = aps + age_points + chronic_points

        return {
            "apache2": total,
            "aps": aps,
            "age_points": age_points,
            "chronic_health_points": chronic_points,
            "breakdown": breakdown,
            "note": (
                "ICU入室24時間以内の最悪値を入力すること。"
                "死亡率推定は疾患別の係数が必要であり本関数では返さない。"
            ),
        }

    def calc_sofa(
        self,
        # 呼吸 (PaO2/FiO2)
        pao2_fio2_ratio: Optional[float] = None,
        mechanical_ventilation: bool = False,
        # 凝固
        plt_10e4_ul: Optional[float] = None,
        # 肝
        bilirubin_mg_dl: Optional[float] = None,
        # 循環
        map_mmhg: Optional[float] = None,
        vasopressor: Literal[
            "none",
            "dopamine_low",        # ≤5 µg/kg/min または ドブタミンのみ
            "dopamine_mid",        # 5.1-15 µg/kg/min または ノルアド/エピネ ≤0.1 µg/kg/min
            "dopamine_high",       # >15 µg/kg/min または ノルアド/エピネ >0.1 µg/kg/min
        ] = "none",
        # 中枢神経
        gcs: Optional[int] = None,
        # 腎
        cr_mg_dl: Optional[float] = None,
        urine_output_ml_per_day: Optional[float] = None,
    ) -> Dict[str, Any]:
        """SOFA (Sequential Organ Failure Assessment) スコアを計算する。
        敗血症診断 (Sepsis-3) や ICU での経時的評価に使用。

        :param pao2_fio2_ratio: PaO2/FiO2比 (mmHg)。例: PaO2 80, FiO2 0.4 なら 200
        :param mechanical_ventilation: 機械換気中か (P/F<200 のスコア判定で使用)
        :param plt_10e4_ul: 血小板 (×10^4/µL、日本表記)
        :param bilirubin_mg_dl: 総ビリルビン (mg/dL)
        :param map_mmhg: 平均動脈圧 (mmHg)
        :param vasopressor: 昇圧剤の使用状況。詳細は下記
        :param gcs: GCS合計
        :param cr_mg_dl: 血清Cr (mg/dL)
        :param urine_output_ml_per_day: 1日尿量 (mL/day)
        :return: {sofa, breakdown, missing_organs, note}

        昇圧剤カテゴリ:
        - none: 昇圧剤なし
        - dopamine_low: ドパミン ≤5 µg/kg/min または ドブタミンのみ
        - dopamine_mid: ドパミン 5.1-15 または ノルアド/エピネ ≤0.1 µg/kg/min
        - dopamine_high: ドパミン >15 または ノルアド/エピネ >0.1 µg/kg/min

        欠損項目はスコアに含めず breakdown を None として返す。
        """
        breakdown: Dict[str, Optional[int]] = {}
        missing = []

        # 呼吸
        if pao2_fio2_ratio is not None:
            if pao2_fio2_ratio >= 400:
                pts = 0
            elif pao2_fio2_ratio >= 300:
                pts = 1
            elif pao2_fio2_ratio >= 200:
                pts = 2
            elif pao2_fio2_ratio >= 100:
                pts = 3 if mechanical_ventilation else 2
            else:
                pts = 4 if mechanical_ventilation else 2
            breakdown["respiration"] = pts
        else:
            breakdown["respiration"] = None
            missing.append("respiration (PaO2/FiO2)")

        # 凝固 (PLTは ×10^9/L で定義されているが、日本表記 ×10^4/µL は同値*10)
        if plt_10e4_ul is not None:
            plt_10e9_l = plt_10e4_ul * 10  # ×10^9/L 換算
            if plt_10e9_l >= 150: pts = 0
            elif plt_10e9_l >= 100: pts = 1
            elif plt_10e9_l >= 50: pts = 2
            elif plt_10e9_l >= 20: pts = 3
            else: pts = 4
            breakdown["coagulation"] = pts
        else:
            breakdown["coagulation"] = None
            missing.append("coagulation (PLT)")

        # 肝
        if bilirubin_mg_dl is not None:
            if bilirubin_mg_dl < 1.2: pts = 0
            elif bilirubin_mg_dl < 2.0: pts = 1
            elif bilirubin_mg_dl < 6.0: pts = 2
            elif bilirubin_mg_dl < 12.0: pts = 3
            else: pts = 4
            breakdown["liver"] = pts
        else:
            breakdown["liver"] = None
            missing.append("liver (bilirubin)")

        # 循環
        if vasopressor == "dopamine_high":
            pts = 4
        elif vasopressor == "dopamine_mid":
            pts = 3
        elif vasopressor == "dopamine_low":
            pts = 2
        elif map_mmhg is not None:
            pts = 1 if map_mmhg < 70 else 0
        else:
            pts = None
            missing.append("cardiovascular (MAP or vasopressor)")
        breakdown["cardiovascular"] = pts

        # 中枢神経
        if gcs is not None:
            if gcs == 15: pts = 0
            elif gcs >= 13: pts = 1
            elif gcs >= 10: pts = 2
            elif gcs >= 6: pts = 3
            else: pts = 4
            breakdown["cns"] = pts
        else:
            breakdown["cns"] = None
            missing.append("cns (GCS)")

        # 腎
        cr_pts = None
        uo_pts = None
        if cr_mg_dl is not None:
            if cr_mg_dl < 1.2: cr_pts = 0
            elif cr_mg_dl < 2.0: cr_pts = 1
            elif cr_mg_dl < 3.5: cr_pts = 2
            elif cr_mg_dl < 5.0: cr_pts = 3
            else: cr_pts = 4
        if urine_output_ml_per_day is not None:
            if urine_output_ml_per_day < 200: uo_pts = 4
            elif urine_output_ml_per_day < 500: uo_pts = 3

        if cr_pts is not None and uo_pts is not None:
            renal_pts = max(cr_pts, uo_pts)
        elif cr_pts is not None:
            renal_pts = cr_pts
        elif uo_pts is not None:
            renal_pts = uo_pts
        else:
            renal_pts = None
            missing.append("renal (Cr or urine output)")
        breakdown["renal"] = renal_pts

        total = sum(v for v in breakdown.values() if v is not None)

        return {
            "sofa": total,
            "breakdown": breakdown,
            "missing_organs": missing,
            "note": (
                "Sepsis-3定義: 感染症に伴うSOFA急上昇 (≥2点) で敗血症と判断。"
                "経時的評価では同一患者でのトレンドが重要。"
                "本関数は欠損項目をスコアに含めない (0点ではなくNone扱い)。"
                "全項目が揃わない場合、欠損項目を補完してから再計算することを推奨。"
            ),
        }

    # =========================================================================
    # 消化器
    # =========================================================================

    def calc_glasgow_blatchford(
        self,
        bun_mg_dl: float,
        hb_g_dl: float,
        sex: Literal["M", "F"],
        sbp_mmhg: int,
        hr: int,
        melena: bool,
        syncope: bool,
        hepatic_disease: bool,
        cardiac_failure: bool,
    ) -> Dict[str, Any]:
        """Glasgow-Blatchford Score (GBS) を計算する (上部消化管出血のリスク層別)。

        :param bun_mg_dl: BUN (mg/dL)
        :param hb_g_dl: ヘモグロビン (g/dL)
        :param sex: 性別 ("M"/"F")
        :param sbp_mmhg: 収縮期血圧 (mmHg)
        :param hr: 心拍数 (/min)
        :param melena: 黒色便あり
        :param syncope: 失神あり
        :param hepatic_disease: 肝疾患の既往
        :param cardiac_failure: 心不全の既往
        :return: {gbs, risk_category, note}
        """
        score = 0

        # BUN
        if bun_mg_dl >= 70: score += 6
        elif bun_mg_dl >= 28: score += 4
        elif bun_mg_dl >= 22.4: score += 3
        elif bun_mg_dl >= 18.2: score += 2

        # Hb (性別別閾値)
        if sex == "M":
            if hb_g_dl < 10: score += 6
            elif hb_g_dl < 12: score += 3
            elif hb_g_dl < 13: score += 1
        else:
            if hb_g_dl < 10: score += 6
            elif hb_g_dl < 12: score += 1

        # SBP
        if sbp_mmhg < 90: score += 3
        elif sbp_mmhg < 100: score += 2
        elif sbp_mmhg < 110: score += 1

        # その他
        if hr >= 100: score += 1
        if melena: score += 1
        if syncope: score += 2
        if hepatic_disease: score += 2
        if cardiac_failure: score += 2

        # リスク評価
        if score == 0:
            cat = "very_low (外来管理を考慮可能)"
        elif score <= 3:
            cat = "low"
        elif score <= 7:
            cat = "moderate"
        else:
            cat = "high (緊急介入の検討)"

        return {
            "gbs": score,
            "risk_category": cat,
            "note": "GBS=0は外来管理の候補。≥7では介入が必要となることが多い。",
        }

    def calc_ranson_criteria(
        self,
        timing: Literal["admission", "48h"],
        # 入院時項目
        age: Optional[int] = None,
        wbc_10e3_ul: Optional[float] = None,
        glucose_mg_dl: Optional[float] = None,
        ldh_u_l: Optional[float] = None,
        ast_u_l: Optional[float] = None,
        # 48時間項目
        hct_drop_pct: Optional[float] = None,
        bun_increase_mg_dl: Optional[float] = None,
        ca_mg_dl: Optional[float] = None,
        pao2_mmhg: Optional[float] = None,
        base_deficit: Optional[float] = None,
        fluid_sequestration_l: Optional[float] = None,
        # 病因
        gallstone_etiology: bool = False,
    ) -> Dict[str, Any]:
        """Ransonクライテリアを計算する (急性膵炎の重症度評価)。
        入院時5項目と48時間後6項目を別々に評価する。

        :param timing: "admission" (入院時) または "48h" (48時間後)
        :param gallstone_etiology: 胆石性膵炎の場合 True (閾値が一部変わる)
        :return: {timing, score, criteria_met, note}

        注意: 国内では JSS-CT grade や厚労省重症度判定基準のほうが使われる。
              本関数は欧米由来のRansonをそのまま実装。
        """
        criteria_met = []

        if timing == "admission":
            # 胆石性 vs 非胆石性で閾値が異なる
            if gallstone_etiology:
                age_th, wbc_th, glu_th, ldh_th, ast_th = 70, 18, 220, 400, 250
            else:
                age_th, wbc_th, glu_th, ldh_th, ast_th = 55, 16, 200, 350, 250

            if age is not None and age > age_th:
                criteria_met.append(f"age>{age_th}")
            if wbc_10e3_ul is not None and wbc_10e3_ul > wbc_th:
                criteria_met.append(f"WBC>{wbc_th}")
            if glucose_mg_dl is not None and glucose_mg_dl > glu_th:
                criteria_met.append(f"glucose>{glu_th}")
            if ldh_u_l is not None and ldh_u_l > ldh_th:
                criteria_met.append(f"LDH>{ldh_th}")
            if ast_u_l is not None and ast_u_l > ast_th:
                criteria_met.append(f"AST>{ast_th}")

        elif timing == "48h":
            if hct_drop_pct is not None and hct_drop_pct > 10:
                criteria_met.append("Hct drop>10%")
            if bun_increase_mg_dl is not None and bun_increase_mg_dl > 5:
                criteria_met.append("BUN increase>5")
            if ca_mg_dl is not None and ca_mg_dl < 8:
                criteria_met.append("Ca<8")
            if pao2_mmhg is not None and pao2_mmhg < 60:
                criteria_met.append("PaO2<60")
            if base_deficit is not None and base_deficit > 4:
                criteria_met.append("base deficit>4")
            if fluid_sequestration_l is not None and fluid_sequestration_l > 6:
                criteria_met.append("fluid sequestration>6L")

        return {
            "timing": timing,
            "score": len(criteria_met),
            "criteria_met": criteria_met,
            "note": (
                "入院時+48時間後の合計≥3で重症膵炎を疑う。"
                "国内では JSS-CT grade / 厚労省重症度判定基準の併用を推奨。"
            ),
        }

    # =========================================================================
    # 血液 / 凝固
    # =========================================================================

    def calc_dic_score(
        self,
        criteria: Literal["isth_overt", "jmhw_hematologic", "jmhw_non_hematologic"],
        plt_10e4_ul: float,
        fdp_ug_ml: Optional[float] = None,
        d_dimer_ug_ml: Optional[float] = None,
        fibrinogen_mg_dl: Optional[float] = None,
        pt_ratio: Optional[float] = None,
        pt_seconds_prolongation: Optional[float] = None,
        underlying_disease: bool = True,
        bleeding_symptom: bool = False,
        organ_failure: bool = False,
    ) -> Dict[str, Any]:
        """DIC診断スコアを計算する (ISTH overt / 厚労省2017年改定 造血障害型・非造血障害型)。

        :param criteria: "isth_overt" / "jmhw_hematologic" / "jmhw_non_hematologic"
        :param plt_10e4_ul: 血小板 (×10^4/µL、日本表記)
        :param fdp_ug_ml: FDP (µg/mL)
        :param d_dimer_ug_ml: D-dimer (µg/mL)。ISTHではFDPの代用可。
        :param fibrinogen_mg_dl: フィブリノゲン (mg/dL)
        :param pt_ratio: PT比 (国内基準で使用)
        :param pt_seconds_prolongation: PT延長秒数 (ISTHで使用)
        :param underlying_disease: DIC発症の基礎疾患の存在
        :param bleeding_symptom: 出血症状あり (国内基準のみ)
        :param organ_failure: 臓器症状あり (国内基準のみ)
        :return: {criteria, score, threshold_for_dic, dic_diagnosis, breakdown}

        注意: 厚労省基準は2017年改定版を実装。造血障害型は血小板項目を除外する。
        """
        score = 0
        breakdown = {}

        if criteria == "isth_overt":
            # 基礎疾患必須
            if not underlying_disease:
                return {"error": "ISTH overt DICは基礎疾患の存在が前提。"}

            # PLT
            if plt_10e4_ul < 5: pts = 2
            elif plt_10e4_ul < 10: pts = 1
            else: pts = 0
            score += pts; breakdown["plt"] = pts

            # FDP or D-dimer (元の摩耗マーカー)
            marker = fdp_ug_ml if fdp_ug_ml is not None else d_dimer_ug_ml
            if marker is None:
                return {"error": "FDPまたはD-dimerのいずれかが必要。"}
            # ISTH原著はFDPで定義 (>=10で2点, >=5で1点等の閾値はラボ依存)
            # ここでは中等度上昇=2、軽度上昇=3として簡易判定
            # 注: 実装では各施設の基準値で再調整推奨
            if marker >= 25: pts = 3  # strong increase
            elif marker >= 5: pts = 2  # moderate increase
            elif marker > 1: pts = 0  # no increase
            else: pts = 0
            score += pts; breakdown["fibrin_marker"] = pts

            # PT延長 (秒)
            if pt_seconds_prolongation is not None:
                if pt_seconds_prolongation >= 6: pts = 2
                elif pt_seconds_prolongation >= 3: pts = 1
                else: pts = 0
                score += pts; breakdown["pt_prolongation"] = pts

            # フィブリノゲン
            if fibrinogen_mg_dl is not None:
                pts = 1 if fibrinogen_mg_dl < 100 else 0
                score += pts; breakdown["fibrinogen"] = pts

            return {
                "criteria": "ISTH overt DIC (2001)",
                "score": score,
                "threshold_for_dic": 5,
                "dic_diagnosis": score >= 5,
                "breakdown": breakdown,
                "note": "≥5でovert DIC。<5でnon-overt DIC、経時的再評価を要する。",
            }

        elif criteria in ("jmhw_hematologic", "jmhw_non_hematologic"):
            is_hematologic = criteria == "jmhw_hematologic"

            # 基礎疾患
            if underlying_disease:
                score += 1; breakdown["underlying_disease"] = 1

            # 臨床症状
            if bleeding_symptom and not is_hematologic:
                # 造血障害型では出血症状を採点しない (血小板低下によるため)
                score += 1; breakdown["bleeding"] = 1
            if organ_failure:
                score += 1; breakdown["organ_failure"] = 1

            # 血小板 (造血障害型では採点しない)
            if not is_hematologic:
                if plt_10e4_ul < 5: pts = 3
                elif plt_10e4_ul < 8: pts = 2
                elif plt_10e4_ul < 12: pts = 1
                else: pts = 0
                score += pts; breakdown["plt"] = pts

            # FDP
            if fdp_ug_ml is not None:
                if fdp_ug_ml >= 40: pts = 3
                elif fdp_ug_ml >= 20: pts = 2
                elif fdp_ug_ml >= 10: pts = 1
                else: pts = 0
                score += pts; breakdown["fdp"] = pts

            # フィブリノゲン
            if fibrinogen_mg_dl is not None:
                if fibrinogen_mg_dl < 100: pts = 2
                elif fibrinogen_mg_dl < 150: pts = 1
                else: pts = 0
                score += pts; breakdown["fibrinogen"] = pts

            # PT比
            if pt_ratio is not None:
                if pt_ratio >= 1.67: pts = 2
                elif pt_ratio >= 1.25: pts = 1
                else: pts = 0
                score += pts; breakdown["pt_ratio"] = pts

            threshold = 4 if is_hematologic else 7
            return {
                "criteria": (
                    "厚労省 造血障害型 (2017)" if is_hematologic
                    else "厚労省 非造血障害型 (2017)"
                ),
                "score": score,
                "threshold_for_dic": threshold,
                "dic_diagnosis": score >= threshold,
                "breakdown": breakdown,
                "note": (
                    "造血障害型≥4、非造血障害型≥7でDIC。"
                    "白血病等の造血器腫瘍では造血障害型を選択する。"
                ),
            }

    # =========================================================================
    # 酸塩基
    # =========================================================================

    def calc_acid_base_analysis(
        self,
        ph: float,
        pco2: float,
        hco3: float,
        na: Optional[float] = None,
        cl: Optional[float] = None,
        albumin_g_dl: Optional[float] = None,
    ) -> Dict[str, Any]:
        """動脈血ガスを統合解析する: 一次性異常判定 + 代償予測 + AG計算。

        :param ph: 動脈血pH
        :param pco2: PaCO2 (mmHg)
        :param hco3: HCO3- (mEq/L)
        :param na: 血清Na (mEq/L)。AG計算に必要。
        :param cl: 血清Cl (mEq/L)。AG計算に必要。
        :param albumin_g_dl: アルブミン (g/dL)。補正AGに使用。
        :return: {primary_disorder, expected_compensation, compensation_status,
                  anion_gap, corrected_anion_gap, mixed_disorder_suspected, summary}
        """
        result: Dict[str, Any] = {}

        # 一次性判定
        if ph < 7.35:
            if hco3 < 22:
                primary = "metabolic_acidosis"
            elif pco2 > 45:
                primary = "respiratory_acidosis"
            else:
                primary = "indeterminate_acidemia"
        elif ph > 7.45:
            if hco3 > 26:
                primary = "metabolic_alkalosis"
            elif pco2 < 35:
                primary = "respiratory_alkalosis"
            else:
                primary = "indeterminate_alkalemia"
        else:
            primary = "normal_or_mixed"

        result["primary_disorder"] = primary

        # 代償予測
        expected = None
        comp_status = None
        if primary == "metabolic_acidosis":
            # Winters: 期待PaCO2 = 1.5 × HCO3 + 8 ± 2
            expected = 1.5 * hco3 + 8
            result["expected_compensation"] = (
                f"PaCO2 = {expected-2:.1f}-{expected+2:.1f} mmHg (Winters式)"
            )
            if pco2 < expected - 2:
                comp_status = "respiratory_alkalosis_concomitant (代償を超える低下)"
            elif pco2 > expected + 2:
                comp_status = "respiratory_acidosis_concomitant (代償不十分)"
            else:
                comp_status = "appropriate_compensation"
        elif primary == "metabolic_alkalosis":
            # 期待PaCO2 = HCO3 + 15 (近似)
            expected = hco3 + 15
            result["expected_compensation"] = (
                f"PaCO2 ≈ {expected:.1f} mmHg (簡易式)"
            )
            if pco2 < expected - 5:
                comp_status = "respiratory_alkalosis_concomitant"
            elif pco2 > expected + 5:
                comp_status = "respiratory_acidosis_concomitant"
            else:
                comp_status = "appropriate_compensation"
        elif primary == "respiratory_acidosis":
            # 急性: ΔHCO3 ≈ ΔPaCO2 × 0.1, 慢性: ×0.35
            delta_pco2 = pco2 - 40
            expected_acute = 24 + delta_pco2 * 0.1
            expected_chronic = 24 + delta_pco2 * 0.35
            result["expected_compensation"] = (
                f"急性: HCO3≈{expected_acute:.1f}, 慢性: HCO3≈{expected_chronic:.1f}"
            )
        elif primary == "respiratory_alkalosis":
            delta_pco2 = 40 - pco2
            expected_acute = 24 - delta_pco2 * 0.2
            expected_chronic = 24 - delta_pco2 * 0.5
            result["expected_compensation"] = (
                f"急性: HCO3≈{expected_acute:.1f}, 慢性: HCO3≈{expected_chronic:.1f}"
            )

        if comp_status:
            result["compensation_status"] = comp_status

        # AG計算
        if na is not None and cl is not None:
            ag = na - cl - hco3
            result["anion_gap"] = round(ag, 1)
            if albumin_g_dl is not None:
                # 補正AG: AG + 2.5 × (4 - albumin)
                corrected_ag = ag + 2.5 * (4.0 - albumin_g_dl)
                result["corrected_anion_gap"] = round(corrected_ag, 1)
                result["ag_interpretation"] = (
                    "high_anion_gap" if corrected_ag > 12
                    else "normal_anion_gap"
                )
            else:
                result["ag_interpretation"] = (
                    "high_anion_gap" if ag > 12 else "normal_anion_gap"
                )

        # 簡易サマリ
        result["summary"] = f"primary: {primary}"
        if comp_status and comp_status != "appropriate_compensation":
            result["mixed_disorder_suspected"] = True

        return result

    # =========================================================================
    # 腎機能 (追加分)
    # =========================================================================

    def calc_egfr_jsn(
        self,
        cr: float,
        age: int,
        sex: Literal["M", "F"],
    ) -> Dict[str, Any]:
        """日本人のGFR推算式 (日本腎臓学会 2009) によるeGFRを計算する。
        国内では本式が広く使用されている。

        :param cr: 血清クレアチニン (酵素法、mg/dL)
        :param age: 年齢 (歳)
        :param sex: "M" または "F"
        :return: {egfr, formula, ckd_stage, note}

        式: eGFR = 194 × Cr^(-1.094) × age^(-0.287) × (女性なら ×0.739)
        """
        egfr = 194 * (cr ** -1.094) * (age ** -0.287)
        if sex == "F":
            egfr *= 0.739

        if egfr >= 90:
            stage = "G1"
        elif egfr >= 60:
            stage = "G2"
        elif egfr >= 45:
            stage = "G3a"
        elif egfr >= 30:
            stage = "G3b"
        elif egfr >= 15:
            stage = "G4"
        else:
            stage = "G5"

        return {
            "egfr": round(egfr, 1),
            "unit": "mL/min/1.73m²",
            "formula": "JSN 2009 (日本人GFR推算式)",
            "ckd_stage": stage,
            "note": (
                "酵素法で測定したCrを用いること。Jaffe法のCrは低く出るため不適。"
                "薬剤投与量調整には本値ではなく Cockcroft-Gault によるCCr (絶対値) を使う。"
            ),
        }

    def calc_free_water_deficit(
        self,
        na_measured: float,
        weight_kg: float,
        sex: Literal["M", "F"],
        age: int,
        na_target: float = 140,
    ) -> Dict[str, Any]:
        """高Na血症における自由水欠乏量を計算する。

        :param na_measured: 実測Na (mEq/L)
        :param weight_kg: 体重 (kg)
        :param sex: "M" または "F"
        :param age: 年齢 (歳)。65歳以上はTBW比率を下げる。
        :param na_target: 目標Na (mEq/L)、デフォルト140
        :return: {free_water_deficit_L, tbw_L, note}

        式: 自由水欠乏 = TBW × (実測Na/目標Na - 1)
        TBW比率: 男性0.6, 女性0.5 (高齢者はそれぞれ0.5, 0.45)
        """
        if na_measured <= na_target:
            return {
                "error": (
                    f"実測Na ({na_measured}) が目標Na ({na_target}) 以下のため、"
                    f"自由水欠乏は存在しない。"
                )
            }

        if age >= 65:
            tbw_ratio = 0.50 if sex == "M" else 0.45
        else:
            tbw_ratio = 0.60 if sex == "M" else 0.50

        tbw = weight_kg * tbw_ratio
        deficit = tbw * (na_measured / na_target - 1)
        suggested_24h = deficit / 2  # 慢性想定で半量補正提案

        return {
            "free_water_deficit_L": round(deficit, 2),
            "tbw_L": round(tbw, 2),
            "tbw_ratio_used": tbw_ratio,
            "suggested_24h_volume_L": round(suggested_24h, 2),
            "max_correction_rate": "≤10 mEq/L/24h (慢性) または ≤1 mEq/L/h (急性)",
            "note": (
                "本値は自由水のみの欠乏量。維持輸液量と経口/経管摂取量も別途考慮すること。"
                "Naの急速補正は脳浮腫・脱髄を起こすため、慢性例では24時間で半量補正を目安。"
                "輸液製剤の自由水含量に注意 (5%ブドウ糖=100%、1/2生食=50%、生食=0%)。"
            ),
        }

    # =========================================================================
    # コメントスタブ (Phase 1.5以降で実装候補)
    # =========================================================================
    # 以下、Phase 1のログを見て頻用されるものから順次実装する。
    #
    # def calc_grace_score(...): ACS入院時リスク (急性冠症候群)
    # def calc_timi_score(type, ...): NSTEMI/STEMI 統合
    # def calc_pesi(simplified=False, ...): PE 重症度
    # def calc_bisap(...): 急性膵炎 簡易版
    # def calc_calvert_carboplatin(target_auc, gfr): Calvert式 (GFR上限125)
    # def calc_meld_3(...): MELD 3.0 (UNOS 2023〜)
    # def calc_na_correction_rate(...): Na補正速度の上限警告
    #
    # === TDM (別SKILL扱い) ===
    # バンコマイシン TDM、アミノグリコシド TDM 等は本tool群ではなく、
    # 独立SKILL (vancomycin-tdm 等) として Pyodide ワークフローで実装する。
    # 理由: 計算 → 可視化 → What-if が一連のワークフローで、
    #       tool の単発呼び出しよりも Pyodide 上で対話的に進めるほうが価値が高い。
    #       また各施設の薬剤部 TDM 支援サービスとの役割分担も明確にしやすい。
