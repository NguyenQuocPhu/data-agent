"use client";

import React from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Users, Eye, ShieldAlert } from "lucide-react";
import type { Persona } from "@/components/persona-dashboard";

interface PersonaCardsProps {
  data: Persona[];
}

const RISK_TIER_ORDER = [
  "Nhóm rủi ro cao – cần hành động ưu tiên",
  "Nhóm bị động – theo dõi & cảnh báo",
  "Nhóm cần giữ chân ngay – ưu tiên giữ chân",
];

const RISK_TIER_STYLE: Record<string, { color: string; icon: React.ReactNode }> = {
  "Nhóm rủi ro cao – cần hành động ưu tiên": {
    color: "border-red-400 bg-red-50 dark:bg-red-950/20",
    icon: <AlertTriangle className="h-4 w-4 text-red-500" />,
  },
  "Nhóm bị động – theo dõi & cảnh báo": {
    color: "border-amber-400 bg-amber-50 dark:bg-amber-950/20",
    icon: <Eye className="h-4 w-4 text-amber-500" />,
  },
  "Nhóm cần giữ chân ngay – ưu tiên giữ chân": {
    color: "border-blue-400 bg-blue-50 dark:bg-blue-950/20",
    icon: <ShieldAlert className="h-4 w-4 text-blue-500" />,
  },
};

const PROFILE_ATTRIBUTE_LABELS: Record<string, string> = {
  high_spender_pct: "Tỷ lệ chi tiêu cao",
  avg_fee: "Cước phí trung bình",
  tier_upgrade_rate: "Số lần nâng hạng phân khúc (TB)",
  tier_downgrade_rate: "Số lần tụt hạng phân khúc (TB)",
  usage_decline_strong_pct: "Tỷ lệ giảm sử dụng mạnh",
  usage_decline_mild_pct: "Tỷ lệ giảm sử dụng nhẹ",
  usage_unstable_pct: "Tỷ lệ sử dụng dao động",
  status_worsening_pct: "Tỷ lệ trạng thái thuê bao xấu đi",
  loyalty_rank_avg: "Hạng khách hàng thân thiết (TB)",
  csat_avg: "CSAT trung bình",
  ces_avg: "CES trung bình",
};

// Mirrors triadic_dgm/services/report_generator.py::RETENTION_SCRIPT_CATALOG / attach_recommended_scripts.
// Small (~5 entries) and deterministic — keep both copies in sync if the catalog text changes.
const RETENTION_SCRIPT_CATALOG: Record<string, { category: string; script: string }> = {
  TECHNICAL: {
    category: "Vấn đề kỹ thuật",
    script:
      "Xin lỗi vì trải nghiệm mạng chưa ổn định, xác nhận lại sự cố, cam kết thời gian xử lý, đề xuất kiểm tra đường truyền miễn phí.",
  },
  PRICE: {
    category: "Giá cước cao / Thay đổi hạng phân khúc",
    script:
      "Ghi nhận phản hồi về chi phí, giải thích thay đổi hạng phân khúc (nếu có), đề xuất gói/ưu đãi giữ chân phù hợp theo chính sách hiện hành.",
  },
  EXPERIENCE: {
    category: "Trải nghiệm kém / CSAT thấp",
    script:
      "Xin lỗi về trải nghiệm liên hệ nhiều lần, tổng hợp lịch sử tương tác, xử lý dứt điểm trong 1 lần gọi (FCR), khảo sát lại sau xử lý.",
  },
  NEEDS_CHANGE: {
    category: "Nhu cầu thay đổi (giảm sử dụng)",
    script: "Tìm hiểu lý do giảm nhu cầu sử dụng, tư vấn gói phù hợp hơn với hành vi hiện tại thay vì chỉ giữ nguyên gói cũ.",
  },
  PAYMENT: {
    category: "Dấu hiệu tạm ngưng / nguy cơ rời mạng",
    script:
      "Chủ động liên hệ hỏi thăm tình trạng sử dụng, xác nhận nhu cầu tiếp tục dịch vụ, đề xuất hỗ trợ trước khi khách hàng chuyển sang trạng thái tạm ngưng.",
  },
};

// Mirrors triadic_dgm/services/report_generator.py::FEATURE_SEMANTIC_MAP / EXCLUDED_TECHNICAL_FEATURES /
// CONFLICTING_FEATURE_PAIRS / _DIRECTIONAL_FLAG_FEATURES / _get_business_signal / _top_signals /
// _get_persona_icon / _get_intensity_tag. Ported so the dashboard can render the SAME real evidence
// bullets as the markdown report straight from the raw persona JSON — keep both copies in sync if the
// Python semantic layer changes.
const FEATURE_SEMANTIC_MAP: Record<string, string> = {
  months_since_last_call: "Tần suất liên hệ CSKH",
  months_since_first_call: "Lịch sử liên hệ",
  // LƯU Ý: "cl" = sự cố kỹ thuật (Checklist) — KHÔNG PHẢI "complaint" (phàn nàn/khiếu nại), đây là
  // 2 cột khác nhau trong dataset (đã fix bên report_generator.py's FEATURE_SEMANTIC_MAP nhưng bản
  // port TS này bị bỏ sót, khiến markdown và dashboard hiện 2 cái tên KHÁC NHAU cho cùng 1 feature).
  months_since_last_cl: "Số tháng kể từ lần phát sinh sự cố kỹ thuật gần nhất",
  cl_total_6m: "Tổng số sự cố kỹ thuật (6 tháng)",
  call_total_6m: "Tổng số cuộc gọi",
  missed_total_6m: "Tỷ lệ cuộc gọi không thành công",
  cl_trend: "Xu hướng sự cố kỹ thuật",
  call_trend: "Xu hướng liên hệ",
  complaint_trend: "Xu hướng phàn nàn",
  declining_cl: "Dấu hiệu giảm sự cố kỹ thuật",
  declining_contact: "Dấu hiệu giảm tương tác",
  declining_complaint: "Dấu hiệu giảm phàn nàn",
  escalating_cl: "Dấu hiệu sự cố kỹ thuật leo thang",
  escalating_complaint: "Dấu hiệu phàn nàn leo thang",
  old_complaint: "Lịch sử phàn nàn cũ",
  cl_recent_only: "Sự cố kỹ thuật mới phát sinh",
  no_cl_all_period: "Không phát sinh sự cố kỹ thuật trong toàn kỳ",
  no_complaint_all_period: "Lịch sử phàn nàn",
  call_cv: "Mức độ biến động liên hệ",
  cl_avg_6m: "Mật độ sự cố kỹ thuật trung bình",
  fee_total: "Tổng cước phí",
  fee_avg: "Cước phí trung bình",
  fee_trend: "Xu hướng cước phí",
  high_spender: "Khách hàng chi tiêu cao",
  segment_trend: "Xu hướng hạng phân khúc",
  segment_upgrade_count: "Số lần nâng hạng phân khúc",
  segment_downgrade_count: "Số lần tụt hạng phân khúc",
  spending_decline: "Chi tiêu đang giảm",
  spending_growth: "Chi tiêu đang tăng",
  cnt_giam_nhe: "Số tháng sử dụng giảm nhẹ",
  cnt_giam_manh: "Số tháng sử dụng giảm mạnh",
  cnt_dao_dong: "Số tháng sử dụng dao động",
  persistent_giam_manh: "Xu hướng giảm sử dụng mạnh kéo dài",
  ever_giam_manh: "Từng giảm sử dụng mạnh",
  ever_giam_nhe: "Từng giảm sử dụng nhẹ",
  status_worsening: "Trạng thái thuê bao xấu đi",
  status_trend: "Xu hướng trạng thái thuê bao",
  loyalty_rank: "Hạng khách hàng thân thiết",
  loyalty_status: "Trạng thái khách hàng thân thiết",
  total_csat: "Điểm hài lòng khách hàng (CSAT)",
};

const EXCLUDED_TECHNICAL_FEATURES = new Set(["cluster", "cluster_id", "is_anomaly", "persona_type", "priority_score"]);

const CONFLICTING_FEATURE_PAIRS: [string, string][] = [
  ["spending_growth", "spending_decline"],
  ["segment_upgrade_count", "segment_downgrade_count"],
];

const DIRECTIONAL_FLAG_FEATURES = new Set([
  "persistent_giam_manh", "ever_giam_manh", "ever_giam_nhe",
  "spending_decline", "spending_growth",
  "declining_cl", "declining_contact", "declining_complaint",
  "escalating_cl", "escalating_complaint",
  "status_worsening", "cl_recent_only", "complaint_recent_only",
]);

const SENTINEL_MISSING_VALUES = new Set([999, 888, 500, 500.95, 887, 886.77, 898.38, 898.34]);

// support_pct should always be a 0-1 fraction, but LLM-authored pipeline code can drift and emit
// it already as a 0-100 percentage (confirmed on a live run: a 93.14% cluster rendered as
// "9314.0%" because this display always multiplied by 100). A persona's support_pct can never
// legitimately exceed 1 as a fraction, so treat any value > 1 as already being a percentage.
function toPercent(supportPct: number | undefined): number {
  const v = supportPct || 0;
  return v > 1 ? v : v * 100;
}

function getBusinessSignal(feature: string, val: number, globalMean: number): string {
  const key = feature.toLowerCase();
  const baseName = FEATURE_SEMANTIC_MAP[key] ?? feature;

  if (SENTINEL_MISSING_VALUES.has(val)) {
    if (key.includes("call")) return "Không phát sinh liên hệ trong kỳ";
    // "cl" = sự cố kỹ thuật, KHÔNG PHẢI "complaint" — PHẢI check "complaint" TRƯỚC "cl" vì
    // "declining_complaint" chứa substring "cl" (từ "de-CL-ining"), check "cl" trước sẽ nhận nhầm.
    if (key.includes("complaint")) return "Không có khiếu nại trong kỳ";
    if (key.includes("cl")) return "Không có sự cố kỹ thuật trong kỳ";
    return "Chưa có dữ liệu";
  }

  const deltaPct = globalMean !== 0 ? ((val - globalMean) / Math.abs(globalMean)) * 100 : val * 100;

  if (DIRECTIONAL_FLAG_FEATURES.has(key)) {
    if (deltaPct > 100) return `${baseName} — phổ biến hơn hẳn trong nhóm này`;
    if (deltaPct > 0) return `${baseName} — phổ biến hơn trung bình`;
    if (deltaPct < -100) return `${baseName} — hiếm gặp trong nhóm này`;
    if (deltaPct < 0) return `${baseName} — ít phổ biến hơn trung bình`;
    return `${baseName} — ở mức trung bình`;
  }

  if (deltaPct > 100) return `${baseName} tăng rất mạnh`;
  if (deltaPct > 0) return `${baseName} có xu hướng tăng`;
  if (deltaPct < -100) return `${baseName} giảm rất mạnh`;
  if (deltaPct < 0) return `${baseName} có xu hướng giảm`;
  return `${baseName} ổn định`;
}

type Deviation = [feature: string, val: number, globalVal: number, devScore: number];

function getMeans(p: Persona): Record<string, number> {
  const means = p.feature_means ?? p.evidence ?? {};
  const out: Record<string, number> = {};
  for (const [f, v] of Object.entries(means)) {
    if (!EXCLUDED_TECHNICAL_FEATURES.has(f.toLowerCase())) out[f] = v;
  }
  return out;
}

function rankedDeviations(means: Record<string, number>, globalMeans: Record<string, number>): Deviation[] {
  const devs: Deviation[] = Object.entries(means).map(([f, val]) => {
    const g = globalMeans[f] ?? 0;
    const dev = g !== 0 ? Math.abs(val - g) / Math.abs(g) : Math.abs(val) * 100;
    return [f, val, g, dev] as Deviation;
  });
  devs.sort((a, b) => b[3] - a[3]);
  return devs;
}

function resolveConflicts(devs: Deviation[]): Deviation[] {
  const names = devs.map((d) => d[0]);
  const dropped = new Set<string>();
  for (const [a, b] of CONFLICTING_FEATURE_PAIRS) {
    const ia = names.indexOf(a);
    const ib = names.indexOf(b);
    if (ia !== -1 && ib !== -1) {
      dropped.add(devs[ia][3] < devs[ib][3] ? a : b);
    }
  }
  return devs.filter((d) => !dropped.has(d[0]));
}

function computeGlobalMeans(personas: Persona[]): Record<string, number> {
  const totalSupport = personas.reduce((acc, p) => acc + (p.support || 0), 0) || 1;
  const allFeatures = new Set<string>();
  personas.forEach((p) => Object.keys(getMeans(p)).forEach((f) => allFeatures.add(f)));
  const out: Record<string, number> = {};
  allFeatures.forEach((f) => {
    const total = personas.reduce((acc, p) => acc + (getMeans(p)[f] ?? 0) * (p.support || 0), 0);
    out[f] = total / totalSupport;
  });
  return out;
}

// Real evidence bullets only — top-N strongest feature deviations plus the dominant service usage
// if present. Never fabricated commentary; every bullet traces back to a field in the persona JSON.
function getEvidenceBullets(p: Persona, globalMeans: Record<string, number>, topN = 3): string[] {
  const means = getMeans(p);
  const bullets: string[] = [];
  if (Object.keys(means).length > 0) {
    const top = resolveConflicts(rankedDeviations(means, globalMeans)).slice(0, topN);
    for (const [f, val, g] of top) {
      bullets.push(getBusinessSignal(f, val, g));
    }
  }
  // Fallback: some pipeline runs only populate `domain_signature` (6-domain star rating), not
  // `feature_means`/`evidence` (raw clustering-feature means) — without this, any persona whose
  // JSON only has domain_signature silently shows "Không có tín hiệu nổi bật" even though real,
  // differentiated signal exists (confirmed on a live run: 3 personas with clearly different
  // profile_attributes all showed "no signal" because feature_means was empty/absent).
  if (bullets.length === 0 && p.domain_signature) {
    const domainEntries = Object.values(p.domain_signature)
      .filter((info) => info && info.stars >= 2 && Array.isArray(info.top_features) && info.top_features.length > 0)
      .sort((a, b) => b.stars - a.stars);
    for (const info of domainEntries.slice(0, topN)) {
      const feat = info.top_features[0];
      if (Array.isArray(feat) && feat.length >= 3) {
        bullets.push(getBusinessSignal(feat[0], feat[1], feat[2]));
      }
    }
  }
  const svcComp = p.profile_attributes?.service_composition;
  if (svcComp && Object.keys(svcComp).length > 0) {
    const [topSvc, topPct] = Object.entries(svcComp).sort((a, b) => b[1] - a[1])[0];
    bullets.push(`Đa số là KH dùng dịch vụ ${topSvc} (${(topPct * 100).toFixed(1)}%)`);
  }
  return bullets.length > 0 ? bullets : ["Không có tín hiệu nổi bật so với trung bình"];
}

const PERSONA_ICON_RULES: [string[], string][] = [
  [["chi tiêu cao có dấu hiệu suy giảm"], "💎📉"],
  [["chi tiêu cao"], "💎"],
  [["bất mãn"], "😞"],
  [["tạm ngưng"], "⚠️"],
  [["hạ cấp", "suy giảm mạnh", "giảm sử dụng"], "📉"],
  [["dao động"], "🔀"],
  [["nâng cấp"], "📈"],
  [["giảm gắn bó"], "🔌"],
  [["gắn bó"], "🔗"],
  [["liên hệ cskh", "cskh nhiều"], "🎧"],
  [["kỹ thuật"], "🛠️"],
  [["im lặng"], "🔕"],
  [["tương tác nhẹ"], "📵"],
  [["bất thường"], "❗"],
  [["ổn định"], "⚖️"],
];

function getPersonaIcon(name: string): string {
  const n = name.toLowerCase();
  for (const [keywords, icon] of PERSONA_ICON_RULES) {
    if (keywords.some((k) => n.includes(k))) return icon;
  }
  return "👤";
}

function getIntensityTag(p: Persona): string {
  if (p.persona_type === "ANOMALY") return "Anomaly";
  if (p.severity === "EXTREME" || p.risk === "EXTREME") return "Very High Risk";
  const tier = p.risk_tier ?? "";
  if (tier.includes("giữ chân")) return "Priority Retention";
  if (p.severity === "HIGH" || p.risk === "HIGH") return "High Risk";
  if (tier.includes("bị động")) return "Passive";
  if (p.severity === "MEDIUM" || p.risk === "MEDIUM") return "Medium";
  return "Stable";
}

// Mirrors triadic_dgm/services/report_generator.py::ReportGenerator.clean_persona_name — strips the
// dedup suffix ("- Nhóm N") added when 2+ clusters share the same base rule-engine name.
function cleanPersonaName(rawName: string): string {
  let name = rawName;
  if (name.includes(" - Cluster ")) name = name.split(" - Cluster ")[0].trim();
  if (name.includes(" - Nhóm")) name = name.split(" - Nhóm")[0].trim();
  if (name.includes(" - Rank")) name = name.split(" - Rank")[0].trim();
  return name;
}

function attachRecommendedScripts(persona: Persona): { category: string; script: string }[] {
  const profile = persona.profile_attributes || {};
  const scripts: { category: string; script: string }[] = [];
  if (persona.severity === "HIGH" || persona.severity === "EXTREME") {
    scripts.push(RETENTION_SCRIPT_CATALOG.TECHNICAL);
  }
  if ((profile.tier_downgrade_rate ?? 0) > 0) {
    scripts.push(RETENTION_SCRIPT_CATALOG.PRICE);
  }
  if (profile.csat_avg !== undefined && profile.csat_avg <= 2) {
    scripts.push(RETENTION_SCRIPT_CATALOG.EXPERIENCE);
  }
  if (
    (profile.usage_decline_strong_pct ?? 0) >= 0.2 ||
    (profile.usage_decline_mild_pct ?? 0) >= 0.3 ||
    (profile.usage_unstable_pct ?? 0) >= 0.3
  ) {
    scripts.push(RETENTION_SCRIPT_CATALOG.NEEDS_CHANGE);
  }
  if ((profile.status_worsening_pct ?? 0) >= 0.2) {
    scripts.push(RETENTION_SCRIPT_CATALOG.PAYMENT);
  }
  if ((persona.risk === "HIGH" || persona.risk === "EXTREME") && scripts.length === 0) {
    scripts.push(RETENTION_SCRIPT_CATALOG.EXPERIENCE);
  }
  return scripts;
}

export function PersonaCards({ data }: PersonaCardsProps) {
  let actualData = data;
  if (data && !Array.isArray(data) && Array.isArray((data as any).personas)) {
    actualData = (data as any).personas;
  }
  if (!actualData || !Array.isArray(actualData)) {
    return null;
  }

  const hasRiskTier = actualData.some((p) => p.risk_tier);
  const hasProfileAttributes = actualData.some(
    (p) => p.profile_attributes && Object.keys(p.profile_attributes).length > 0
  );
  const globalMeans = computeGlobalMeans(actualData);

  return (
    <div className="w-full my-6 space-y-4 font-sans">
      {/* Persona Overview Cards — icon + % + real evidence bullets (top feature deviations +
          dominant service usage). Mirrors report_generator.py's Persona Overview section so the
          dashboard and the markdown report always state the same facts. */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {actualData.map((p) => {
          const name = cleanPersonaName(p.persona_name);
          const icon = getPersonaIcon(name);
          const tag = getIntensityTag(p);
          const bullets = getEvidenceBullets(p, globalMeans, 3);
          const tierStyle = p.risk_tier ? RISK_TIER_STYLE[p.risk_tier] : undefined;
          const borderColor = tierStyle?.color ?? "border-gray-300 bg-gray-50 dark:bg-gray-900/20";
          return (
            <Card key={p.cluster_id} className={`border-2 ${borderColor}`}>
              <CardHeader className="flex flex-row items-start gap-3 space-y-0 pb-2">
                <div className="text-3xl leading-none" aria-hidden="true">
                  {icon}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-muted-foreground">
                    Cụm {p.cluster_id} · {tag}
                  </p>
                  <CardTitle className="text-base leading-snug">{name}</CardTitle>
                  <p className="text-sm font-semibold">{toPercent(p.support_pct).toFixed(1)}%</p>
                </div>
              </CardHeader>
              <CardContent>
                <ul className="text-xs space-y-1 list-disc pl-4">
                  {bullets.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {hasRiskTier && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {RISK_TIER_ORDER.map((tier) => {
            const personasInTier = actualData.filter((p) => p.risk_tier === tier);
            const style = RISK_TIER_STYLE[tier];
            return (
              <Card key={tier} className={`border-2 ${style.color}`}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">{tier}</CardTitle>
                  {style.icon}
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{personasInTier.length}</div>
                  <p className="text-xs text-muted-foreground">
                    {personasInTier.length > 0
                      ? personasInTier.map((p) => cleanPersonaName(p.persona_name)).join(", ")
                      : "Không có persona nào"}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {hasProfileAttributes && (
        <Card className="w-full">
          <CardHeader>
            <CardTitle>Persona Profile Details</CardTitle>
            <CardDescription>Thuộc tính mô tả &amp; kịch bản giữ chân theo từng persona</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {actualData.map((p) => {
              const profile = p.profile_attributes || {};
              const profileKeys = Object.keys(profile).filter((k) => k in PROFILE_ATTRIBUTE_LABELS);
              const scripts =
                p.risk_tier?.includes("giữ chân") || p.severity === "HIGH" || p.severity === "EXTREME" || p.risk === "HIGH" || p.risk === "EXTREME"
                  ? attachRecommendedScripts(p)
                  : [];

              if (profileKeys.length === 0 && scripts.length === 0) return null;

              return (
                <div key={p.cluster_id} className="border rounded-md p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Users className="h-4 w-4 text-muted-foreground" />
                    <span className="font-semibold text-sm">{cleanPersonaName(p.persona_name)}</span>
                    {p.risk_tier && <Badge variant="outline">{p.risk_tier}</Badge>}
                  </div>

                  {profileKeys.length > 0 && (
                    <ul className="text-xs text-muted-foreground list-disc pl-5 mb-2">
                      {profileKeys.map((k) => (
                        <li key={k}>
                          {PROFILE_ATTRIBUTE_LABELS[k]}: {String((profile as any)[k])}
                        </li>
                      ))}
                    </ul>
                  )}

                  {scripts.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <p className="text-xs font-medium">Retention Scripts:</p>
                      {scripts.map((s, i) => (
                        <p key={i} className="text-xs text-muted-foreground">
                          <span className="font-medium">{s.category}:</span> {s.script}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
