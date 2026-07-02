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

  return (
    <div className="w-full my-6 space-y-4 font-sans">
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
                      ? personasInTier.map((p) => p.persona_name).join(", ")
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
                    <span className="font-semibold text-sm">{p.persona_name}</span>
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
