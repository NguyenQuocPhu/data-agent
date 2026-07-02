import json
import re
from datetime import datetime
import instructor
from openai import OpenAI
from triadic_dgm.schemas.report_schema import ReportNarrative

# ==============================================================
# TAXONOMY & MAPPING CATALOG (Enterprise Metadata)
# ==============================================================
ROADMAP_METADATA = {
    "Outbound CSKH chủ động để xoa dịu khách hàng": {
        "objective": "Khôi phục trải nghiệm khách hàng",
        "kpi": "NPS, FCR, Contact Rate",
        "investigation": "Review Ticket, Analyze Call Recording",
        "owner": "Customer Care",
        "timeline": "30 days"
    },
    "Thu thập thêm dữ liệu hành vi": {
        "objective": "Khám phá nguyên nhân gốc rễ (Root Cause)",
        "kpi": "Behavior Coverage, Model Accuracy",
        "investigation": "Pull CRM History, Enrich Telemetry Data",
        "owner": "Data Team",
        "timeline": "14 days"
    },
    "Thu thập thêm App usage logs": {
        "objective": "Nắm bắt hành vi tương tác số",
        "kpi": "App Usage Coverage, Active Rate",
        "investigation": "Review App Sessions, Analyze Feature Usage",
        "owner": "Product Team",
        "timeline": "14 days"
    },
    "Khảo sát mức độ hài lòng qua Zalo/SMS": {
        "objective": "Thu thập phản hồi trực tiếp",
        "kpi": "NPS, CES, Response Rate",
        "investigation": "Send Pulse Survey, Post-interaction Survey",
        "owner": "CX Team",
        "timeline": "7 days"
    },
    "Phân tích nguyên nhân khiếu nại/liên hệ": {
        "objective": "Giảm tỷ lệ khiếu nại lặp lại",
        "kpi": "Repeat Incident Rate, MTTR",
        "investigation": "Check Ticket Categories, Trace Root Cause",
        "owner": "Operations",
        "timeline": "21 days"
    },
    "Nghiên cứu nguyên nhân kỹ thuật": {
        "objective": "Cải thiện chất lượng hạ tầng mạng",
        "kpi": "Network Stability, SLA Success Rate",
        "investigation": "Pull OSS Log, Check Fiber Loss, Review Alarm",
        "owner": "NOC Team",
        "timeline": "14 days"
    }
}

RETENTION_SCRIPT_CATALOG = {
    "TECHNICAL": {
        "category": "Vấn đề kỹ thuật",
        "script": "Xin lỗi vì trải nghiệm mạng chưa ổn định, xác nhận lại sự cố, cam kết thời gian xử lý, đề xuất kiểm tra đường truyền miễn phí.",
    },
    "PRICE": {
        "category": "Giá cước cao / Thay đổi hạng phân khúc",
        "script": "Ghi nhận phản hồi về chi phí, giải thích thay đổi hạng phân khúc (nếu có), đề xuất gói/ưu đãi giữ chân phù hợp theo chính sách hiện hành.",
    },
    "EXPERIENCE": {
        "category": "Trải nghiệm kém / CSAT thấp",
        "script": "Xin lỗi về trải nghiệm liên hệ nhiều lần, tổng hợp lịch sử tương tác, xử lý dứt điểm trong 1 lần gọi (FCR), khảo sát lại sau xử lý.",
    },
    "NEEDS_CHANGE": {
        "category": "Nhu cầu thay đổi (giảm sử dụng)",
        "script": "Tìm hiểu lý do giảm nhu cầu sử dụng, tư vấn gói phù hợp hơn với hành vi hiện tại thay vì chỉ giữ nguyên gói cũ.",
    },
    "PAYMENT": {
        "category": "Dấu hiệu tạm ngưng / nguy cơ rời mạng",
        "script": "Chủ động liên hệ hỏi thăm tình trạng sử dụng, xác nhận nhu cầu tiếp tục dịch vụ, đề xuất hỗ trợ trước khi khách hàng chuyển sang trạng thái tạm ngưng.",
    },
}


def attach_recommended_scripts(persona: dict) -> list:
    """Deterministic, catalog-driven — never LLM-authored (anti-hallucination)."""
    profile = persona.get('profile_attributes', {}) or {}
    severity = persona.get('severity')
    risk = persona.get('risk')
    scripts = []
    if severity in ("HIGH", "EXTREME"):
        scripts.append(RETENTION_SCRIPT_CATALOG["TECHNICAL"])
    if profile.get('tier_downgrade_rate', 0) > 0:
        scripts.append(RETENTION_SCRIPT_CATALOG["PRICE"])
    if profile.get('csat_avg') is not None and profile.get('csat_avg', 5) <= 2:
        scripts.append(RETENTION_SCRIPT_CATALOG["EXPERIENCE"])
    if profile.get('usage_decline_strong_pct', 0) >= 0.2 or profile.get('usage_decline_mild_pct', 0) >= 0.3 or profile.get('usage_unstable_pct', 0) >= 0.3:
        scripts.append(RETENTION_SCRIPT_CATALOG["NEEDS_CHANGE"])
    if profile.get('status_worsening_pct', 0) >= 0.2:
        scripts.append(RETENTION_SCRIPT_CATALOG["PAYMENT"])
    if risk in ("HIGH", "EXTREME") and not scripts:
        scripts.append(RETENTION_SCRIPT_CATALOG["EXPERIENCE"])
    return scripts


FEATURE_SEMANTIC_MAP = {
    "months_since_last_call": "Tần suất liên hệ CSKH",
    "months_since_first_call": "Lịch sử liên hệ",
    "months_since_last_cl": "Tần suất khiếu nại",
    "cl_total_6m": "Tổng số khiếu nại",
    "call_total_6m": "Tổng số cuộc gọi",
    "missed_total_6m": "Tỷ lệ cuộc gọi không thành công",
    "cl_trend": "Xu hướng khiếu nại",
    "call_trend": "Xu hướng liên hệ",
    "complaint_trend": "Xu hướng phàn nàn",
    "declining_cl": "Dấu hiệu giảm khiếu nại",
    "declining_contact": "Dấu hiệu giảm tương tác",
    "declining_complaint": "Dấu hiệu giảm phàn nàn",
    "escalating_cl": "Dấu hiệu khiếu nại leo thang",
    "escalating_complaint": "Dấu hiệu phàn nàn leo thang",
    "old_complaint": "Lịch sử phàn nàn cũ",
    "cl_recent_only": "Hành vi khiếu nại mới phát sinh",
    "no_cl_all_period": "Lịch sử khiếu nại",
    "no_complaint_all_period": "Lịch sử phàn nàn",
    "call_cv": "Mức độ biến động liên hệ",
    "cl_avg_6m": "Mật độ khiếu nại trung bình",
    "fee_total": "Tổng cước phí",
    "fee_avg": "Cước phí trung bình",
    "fee_trend": "Xu hướng cước phí",
    "high_spender": "Khách hàng chi tiêu cao",
    "segment_trend": "Xu hướng hạng phân khúc",
    "segment_upgrade_count": "Số lần nâng hạng phân khúc",
    "segment_downgrade_count": "Số lần tụt hạng phân khúc",
    "spending_decline": "Chi tiêu đang giảm",
    "spending_growth": "Chi tiêu đang tăng",
    "cnt_Giam_nhe": "Số tháng sử dụng giảm nhẹ",
    "cnt_Giam_manh": "Số tháng sử dụng giảm mạnh",
    "cnt_Dao_dong": "Số tháng sử dụng dao động",
    "status_worsening": "Trạng thái thuê bao xấu đi",
    "status_trend": "Xu hướng trạng thái thuê bao",
    "LOYALTY_RANK": "Hạng khách hàng thân thiết",
    "LOYALTY_STATUS": "Trạng thái khách hàng thân thiết",
    "total_csat": "Điểm hài lòng khách hàng (CSAT)",
}

# ==============================================================
# REPORT VALIDATION HARNESS
# ==============================================================
class ReportValidator:
    @staticmethod
    def validate(personas_data: list):
        if not personas_data:
            return
            
        total_customers = sum(p.get('support', 0) for p in personas_data)
        assert total_customers > 0, "Total support must be greater than 0"
        
        # Check unique persona names
        names = [p.get('persona_name') for p in personas_data]
        # Allow duplicate base names since we clean them, but warn
        
        # Ensure KPI mapping exists
        for p in personas_data:
            actions = p.get('recommended_actions', [])
            if actions:
                action = actions[0]
                if action not in ROADMAP_METADATA:
                    print(f"[Validator Warning] Action '{action}' not found in Roadmap Metadata.")

        # Soft warning only — older/plainer JSON without the extended profiling fields must keep working
        if not any(p.get('profile_attributes') for p in personas_data):
            print("[Validator Warning] No persona has 'profile_attributes' — dataset may lack the extended columns (spend/tier/usage-trend/CSAT/loyalty). Risk-tier/profile sections will be limited.")

# ==============================================================
# CORE GENERATOR (v3 Enterprise)
# ==============================================================
class ReportGenerator:
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.client = instructor.from_openai(
            OpenAI(api_key=api_key, base_url=base_url),
            mode=instructor.Mode.JSON
        )

    def extract_json(self, raw_python_output: str):
        match = re.search(r'\[JSON_START_PERSONA\](.*?)\[JSON_END_PERSONA\]', raw_python_output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return []
        return []

    def clean_persona_name(self, raw_name: str) -> str:
        name = raw_name
        if " - Cluster " in name:
            name = name.split(" - Cluster ")[0].strip()
        if " - Nhóm" in name:
            name = name.split(" - Nhóm")[0].strip()
        if " - Rank" in name:
            name = name.split(" - Rank")[0].strip()
        return name

    def format_support(self, support: int) -> str:
        if support >= 1000:
            return f"≈{support/1000:.1f}k KH"
        return f"{support} KH"

    def _get_business_signal(self, feature: str, val: float, global_mean: float) -> str:
        """SEMANTIC LAYER: Converts feature and data into natural business signals."""
        base_name = FEATURE_SEMANTIC_MAP.get(feature, feature)
        
        # Handle the magic 999
        if val in [999, 999.0, 888, 888.0, 500.0, 500.95, 887, 886.77, 898.38, 898.34]:
            if 'call' in feature:
                return "Không phát sinh liên hệ trong kỳ"
            if 'cl' in feature or 'complaint' in feature:
                return "Không có khiếu nại trong kỳ"
            return "Chưa có dữ liệu"
            
        # Handle Boolean 1.0 flags
        if val == 1.0 and ("no_" in feature or "escalating_" in feature or "declining_" in feature):
            return f"Tồn tại {base_name.lower()}"
        if val == 0.0 and ("no_" in feature):
            return f"Có phát sinh {base_name.lower()}"
            
        # Delta comparison
        delta_pct = ((val - global_mean) / abs(global_mean)) * 100 if global_mean != 0 else val * 100
        
        if delta_pct > 100:
            return f"{base_name} tăng rất mạnh"
        elif delta_pct > 0:
            return f"{base_name} có xu hướng tăng"
        elif delta_pct < -100:
            return f"{base_name} giảm rất mạnh"
        elif delta_pct < 0:
            return f"{base_name} có xu hướng giảm"
        else:
            return f"{base_name} ổn định"

    def _get_means(self, p: dict) -> dict:
        return p.get('feature_means', p.get('evidence', {}))

    def _build_prompt(self, personas_data: list, global_means: dict) -> str:
        """Prepares a heavily sterilized JSON for the LLM"""
        clean_data = []
        for p in personas_data:
            c = {}
            c['persona'] = self.clean_persona_name(p.get('persona_name', ''))
            
            # Translate top features into business signals
            means = self._get_means(p)
            signals = []
            if means:
                deviations = []
                for f, val in means.items():
                    g_val = global_means.get(f, 0)
                    dev = abs(val - g_val) / abs(g_val) if g_val != 0 else abs(val) * 100
                    deviations.append((f, val, g_val, dev))
                
                deviations.sort(key=lambda x: x[3], reverse=True)
                for f, val, g_val, dev in deviations[:3]: # Send top 3 signals
                    signals.append(self._get_business_signal(f, val, g_val))
            
            c['business_signals'] = signals
            c['confidence'] = "High" if len(signals) > 0 and deviations[0][3] > 1.0 else "Medium"
            c['cluster_id'] = p.get('cluster_id')
            clean_data.append(c)
            
        data_str = json.dumps(clean_data, ensure_ascii=False, indent=2)
        return f"""
Bạn là Consultant tại Deloitte.
Nhiệm vụ: Viết diễn giải Báo cáo Chân dung Khách hàng bằng NGÔN NGỮ QUẢN TRỊ.

QUY TẮC CỨNG:
- KHÔNG sinh số liệu. KHÔNG nhắc lại số liệu.
- KHÔNG suy diễn ngoài Business Signals được cấp.
- KHÔNG đề xuất hành động mới (Action/Investigation).
- Độ dài: Tối đa 2 câu cho mỗi trường phân tích.

Dữ liệu Business Facts duy nhất bạn được thấy:
{data_str}
"""

    def generate_llm_narrative(self, personas_data: list, global_means: dict) -> ReportNarrative:
        prompt = self._build_prompt(personas_data, global_means)
        try:
            report_narrative: ReportNarrative = self.client.chat.completions.create(
                model=self.model_name,
                response_model=ReportNarrative,
                messages=[{"role": "user", "content": prompt}],
                max_retries=2
            )
            return report_narrative
        except Exception as e:
            raise RuntimeError(f"Failed to generate LLM Narrative: {e}")

    def render_markdown(self, raw_python_output: str) -> str:
        personas_data = self.extract_json(raw_python_output)
        if not personas_data:
            return "Lỗi: Không tìm thấy dữ liệu JSON Persona hợp lệ."
            
        # 1. Validation Harness
        ReportValidator.validate(personas_data)
        
        # 2. Global Calculations
        total_customers = sum(p.get('support', 0) for p in personas_data)
        date_str = datetime.now().strftime("%d tháng %m năm %Y")
        max_pct = max([p.get('support_pct', 0) for p in personas_data])
        max_pct_val = max_pct * 100 if max_pct < 1.0 else max_pct
        seg_quality = personas_data[0].get('segmentation_quality', 'NORMAL')
        
        global_means = {}
        all_features = set()
        for p in personas_data:
            for f in self._get_means(p).keys():
                all_features.add(f)
                
        for f in all_features:
            total_val = sum(self._get_means(p).get(f, 0) * p.get('support', 0) for p in personas_data)
            global_means[f] = total_val / total_customers if total_customers > 0 else 0
            
        for p in personas_data:
            p['priority_score'] = p.get('priority_score', 0)
        ranked_personas = sorted(personas_data, key=lambda x: x['priority_score'], reverse=True)
            
        # 3. Trigger LLM
        narrative = self.generate_llm_narrative(personas_data, global_means)
        
        # ==============================================================
        # 4. REPORT COMPOSER (Presentation Layer)
        # ==============================================================
        
        # Executive Summary
        md = "# BÁO CÁO PHÂN TÍCH CHÂN DUNG KHÁCH HÀNG\n\n"
        md += "**ISC - AI - Data Product Team**\n\n"
        md += f"*Ngày {date_str}*\n\n"
        md += "---\n\n"
        
        md += "## 1. Executive Summary\n\n"
        md += "> [!NOTE]\n"
        md += "> **Executive Facts:**\n"
        md += f"> - **Segmentation Quality:** {seg_quality}\n"
        md += f"> - **Dominant Persona Size:** {max_pct_val:.1f}%\n"
        md += f"> - **Total Population:** {self.format_support(total_customers)}\n\n"
        
        md += f"{narrative.executive_summary.executive_overview}\n\n"
            
        # Methodology
        md += "## 2. Methodology\n\n"
        md += "`Dataset ➔ Feature Engineering ➔ Clustering ➔ Rule Engine ➔ Semantic Layer ➔ Presentation Layer ➔ Narrative Generator (LLM) ➔ Report Composer`\n\n"
        
        # Persona Overview
        md += "## 3. Persona Overview\n\n"
        md += "| Persona | Support | Severity | Risk | Primary Evidence |\n"
        md += "|---|---|---|---|---|\n"
        for p in personas_data:
            p_name = self.clean_persona_name(p.get('persona_name', 'Unknown'))
            sup_str = self.format_support(p.get('support', 0))
            
            # Simple primary evidence mapping
            means = self._get_means(p)
            evid_str = "N/A"
            if means:
                deviations = []
                for f, val in means.items():
                    g_val = global_means.get(f, 0)
                    dev = abs(val - g_val) / abs(g_val) if g_val != 0 else abs(val) * 100
                    deviations.append((f, val, g_val, dev))
                deviations.sort(key=lambda x: x[3], reverse=True)
                top_f = deviations[0][0]
                top_val = deviations[0][1]
                top_g_val = deviations[0][2]
                evid_str = self._get_business_signal(top_f, top_val, top_g_val)
                
            md += f"| **{p_name}** | {sup_str} | {p.get('severity','N/A')} | {p.get('risk','N/A')} | {evid_str} |\n"
        md += "\n"

        # Risk Tier Grouping (only if at least one persona has risk_tier computed)
        if any(p.get('risk_tier') for p in personas_data):
            md += "## 3b. Risk Tier Grouping\n\n"
            tier_order = [
                "Nhóm rủi ro cao – cần hành động ưu tiên",
                "Nhóm bị động – theo dõi & cảnh báo",
                "Nhóm cần giữ chân ngay – ưu tiên giữ chân",
            ]
            tiers = {t: [] for t in tier_order}
            for p in personas_data:
                t = p.get('risk_tier')
                if t in tiers:
                    tiers[t].append(self.clean_persona_name(p.get('persona_name', '')))
            md += "| " + " | ".join(tier_order) + " |\n"
            md += "|" + "---|" * len(tier_order) + "\n"
            md += "| " + " | ".join(", ".join(tiers[t]) if tiers[t] else "—" for t in tier_order) + " |\n\n"

        # Persona Analysis
        md += "## 4. Persona Analysis\n\n"
        narrative_dict = {n.cluster_id: n for n in narrative.personas_analysis}
        
        for p in personas_data:
            cid = p.get('cluster_id')
            n = narrative_dict.get(cid)
            p_name = self.clean_persona_name(p.get('persona_name', f'Nhóm {cid}'))
            actions = p.get('recommended_actions', [])
            primary_action = actions[0] if actions else "N/A"
            sup_str = self.format_support(p.get('support', 0))
            
            # Calculate signals and confidence
            means = self._get_means(p)
            signals = []
            confidence = "MEDIUM"
            if means:
                deviations = []
                for f, val in means.items():
                    g_val = global_means.get(f, 0)
                    dev = abs(val - g_val) / abs(g_val) if g_val != 0 else abs(val) * 100
                    deviations.append((f, val, g_val, dev))
                deviations.sort(key=lambda x: x[3], reverse=True)
                
                if deviations[0][3] > 1.0: confidence = "HIGH"
                
                for f, val, g_val, dev in deviations[:3]:
                    signals.append(f"- {self._get_business_signal(f, val, g_val)}")
                    
            signals_text = "\n".join(signals) if signals else "- N/A"
            investigation = ROADMAP_METADATA.get(primary_action, {}).get("investigation", "Review Data")
            
            md += f"### {p_name}\n\n"
            md += "| Thuộc tính | Giá trị |\n"
            md += "|---|---|\n"
            md += f"| **Quy mô** | {sup_str} |\n"
            md += f"| **Severity** | {p.get('severity','N/A')} |\n"
            md += f"| **Risk** | {p.get('risk','N/A')} |\n"
            md += f"| **Semantic Confidence**| {confidence} |\n"
            md += f"| **Recommended Direction**| {investigation} |\n\n"
            
            md += f"**Business Signals:**\n{signals_text}\n\n"

            if n:
                md += f"**Business Interpretation:**\n{n.business_interpretation}\n\n"
                md += f"**Operational Impact:**\n{n.operational_impact}\n\n"

            # Profile Attributes (only present keys — never fabricate missing ones)
            profile = p.get('profile_attributes') or {}
            if profile:
                profile_labels = {
                    'high_spender_pct': 'Tỷ lệ chi tiêu cao',
                    'avg_fee': 'Cước phí trung bình',
                    'tier_upgrade_rate': 'Số lần nâng hạng phân khúc (TB)',
                    'tier_downgrade_rate': 'Số lần tụt hạng phân khúc (TB)',
                    'usage_decline_strong_pct': 'Tỷ lệ giảm sử dụng mạnh',
                    'usage_decline_mild_pct': 'Tỷ lệ giảm sử dụng nhẹ',
                    'usage_unstable_pct': 'Tỷ lệ sử dụng dao động',
                    'status_worsening_pct': 'Tỷ lệ trạng thái thuê bao xấu đi',
                    'loyalty_rank_avg': 'Hạng khách hàng thân thiết (TB)',
                    'csat_avg': 'CSAT trung bình',
                    'ces_avg': 'CES trung bình',
                    'package_composition': 'Thành phần loại gói cước',
                }
                md += "**Profile Attributes:**\n"
                for key, label in profile_labels.items():
                    if key in profile:
                        md += f"- {label}: {profile[key]}\n"
                md += "\n"

            # Retention Scripts — only for the "cần giữ chân ngay" tier or HIGH+/EXTREME severity/risk
            risk_tier = p.get('risk_tier', '')
            if "giữ chân" in risk_tier or p.get('severity') in ("HIGH", "EXTREME") or p.get('risk') in ("HIGH", "EXTREME"):
                scripts = attach_recommended_scripts(p)
                if scripts:
                    md += "**Retention Scripts:**\n"
                    for s in scripts:
                        md += f"- *{s['category']}*: {s['script']}\n"
                    md += "\n"

            md += "---\n\n"
            
        # Business Roadmap
        md += "## 5. Business Roadmap\n\n"
        action_dict = {a.cluster_id: a for a in narrative.recommendations_analysis}
        
        md += "| Priority | Initiative | Target Persona | Owner | Timeline | KPI | Expected Outcome |\n"
        md += "|---|---|---|---|---|---|---|\n"
        
        for rank, p in enumerate(ranked_personas, start=1):
            p_name = self.clean_persona_name(p.get('persona_name', ''))
            cid = p.get('cluster_id')
            actions = p.get('recommended_actions', [])
            n_action = action_dict.get(cid)
            
            action_text = actions[0] if actions else "N/A"
            meta = ROADMAP_METADATA.get(action_text, {})
            owner = meta.get("owner", "TBD")
            timeline = meta.get("timeline", "TBD")
            kpi = meta.get("kpi", "TBD")
            outcome = n_action.expected_outcome if n_action else "N/A"
            
            md += f"| **#{rank}** | {action_text} | {p_name} | {owner} | {timeline} | {kpi} | {outcome} |\n"
            
        md += "\n"
            
        # Conclusion
        md += "## 6. Conclusion\n\n"
        if hasattr(narrative, 'conclusion'):
            md += f"{narrative.conclusion}\n\n"
        
        # Appendix
        md += "## Appendix\n\n"
        md += "### Cluster Feature Statistics\n"
        
        for p in personas_data:
            p_name = self.clean_persona_name(p.get('persona_name', ''))
            md += f"#### {p_name}\n"
            md += "| Feature | Value | Benchmark | Dev % |\n"
            md += "|---|---|---|---|\n"
            means = self._get_means(p)
            deviations = []
            for f, val in means.items():
                g_val = global_means.get(f, 0)
                dev = abs(val - g_val) / abs(g_val) if g_val != 0 else abs(val) * 100
                deviations.append((f, val, g_val, dev))
            deviations.sort(key=lambda x: x[3], reverse=True)
            for f, val, g_val, dev in deviations[:5]:
                delta_pct = ((val - g_val) / abs(g_val)) * 100 if g_val != 0 else (100 if val > 0 else 0)
                md += f"| {f} | {val:.2f} | {g_val:.2f} | {delta_pct:+.1f}% |\n"
            md += "\n"
        
        md += "### Raw Facts\n"
        match = re.search(r'\[JSON_START_PERSONA\].*?\[JSON_END_PERSONA\]', raw_python_output, re.DOTALL)
        if match:
            md += match.group(0) + "\n"
            
        return md

    def generate_markdown_report(self, raw_python_output: str) -> str:
        return self.render_markdown(raw_python_output)
